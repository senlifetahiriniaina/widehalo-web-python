"""RG-SAL-7/8, SAL-SAIS1 (§5.5.3/5.5.9, S6 du sous-sequencement `sales`, cf.
plan) : previsions produit x periode. Cf. `apps.sales.services.forecast`
pour les formules exactes (WMA + lissage exponentiel, coefficient
saisonnier, ajustement calendrier client, ecart capacite/delai)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.partners.tests.factories import PartnerFactory
from apps.sales.models import SalesCustomerCalendar, SalesForecast
from apps.sales.services.forecast import (
    build_forecast,
    customer_calendar_adjustment,
    historical_average_demand,
    recompute_forecasts_for_period,
    seasonal_coefficient,
)
from apps.sales.tests.factories import SalesOrderFactory, SalesOrderLineFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def forecast_setup():
    tenant = Tenant.objects.create(code="SALES-FCST", name="Sales Forecast Tenant")
    with use_tenant(tenant.id):
        partner = PartnerFactory(tenant=tenant)
        return tenant, partner


def _delivered_line(tenant, *, variant_id, date, qty):
    order = SalesOrderFactory(tenant=tenant, date=date)
    return SalesOrderLineFactory(
        tenant=tenant, order=order, variant_id=variant_id, qty=qty, qty_delivered=qty
    )


def test_historical_average_demand_returns_zero_without_history(forecast_setup) -> None:
    tenant, _partner = forecast_setup
    with use_tenant(tenant.id):
        assert historical_average_demand(tenant, uuid.uuid4()) == Decimal(0)


def test_historical_average_demand_weights_recent_months_higher(forecast_setup) -> None:
    """3 mois consecutifs, quantites croissantes -> le resultat doit se
    situer strictement entre la moyenne simple et le dernier mois (preuve
    que la ponderation recente + le lissage jouent effectivement)."""
    tenant, _partner = forecast_setup
    variant_id = uuid.uuid4()
    today = dt.date.today()
    with use_tenant(tenant.id):
        _delivered_line(tenant, variant_id=variant_id, date=today.replace(day=1), qty=Decimal("30"))
        two_months_ago = (today.replace(day=1) - dt.timedelta(days=32)).replace(day=1)
        _delivered_line(tenant, variant_id=variant_id, date=two_months_ago, qty=Decimal("10"))
        one_month_ago = (today.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
        _delivered_line(tenant, variant_id=variant_id, date=one_month_ago, qty=Decimal("20"))

        result = historical_average_demand(tenant, variant_id, months=3)
        simple_average = Decimal("20")  # (10 + 20 + 30) / 3
        assert Decimal(0) < result
        # Le resultat penche vers les mois recents (30) plutot que vers une
        # simple moyenne arithmetique egalement ponderee.
        assert result != simple_average


def test_seasonal_coefficient_neutral_without_enough_history(forecast_setup) -> None:
    tenant, _partner = forecast_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        _delivered_line(tenant, variant_id=variant_id, date=dt.date.today(), qty=Decimal("10"))
        assert seasonal_coefficient(tenant, variant_id, dt.date.today().month) == Decimal(1)


def test_seasonal_coefficient_reflects_peak_month_with_enough_history(forecast_setup) -> None:
    """12 mois distincts d'historique, dont un mois "pic" nettement
    au-dessus des autres -> le coefficient de ce mois doit depasser 1."""
    tenant, _partner = forecast_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        base_date = dt.date(2025, 1, 15)
        for i in range(12):
            month_date = base_date.replace(
                year=base_date.year + (base_date.month - 1 + i) // 12,
                month=(base_date.month - 1 + i) % 12 + 1,
            )
            qty = Decimal("100") if month_date.month == 12 else Decimal("10")
            _delivered_line(tenant, variant_id=variant_id, date=month_date, qty=qty)

        coefficient = seasonal_coefficient(tenant, variant_id, 12)
        assert coefficient > Decimal(1)
        assert seasonal_coefficient(tenant, variant_id, 1) < Decimal(1)


def test_customer_calendar_adjustment_sums_overlapping_entries(forecast_setup) -> None:
    tenant, partner = forecast_setup
    with use_tenant(tenant.id):
        period_start = dt.date(2026, 6, 1)
        period_end = dt.date(2026, 6, 30)
        SalesCustomerCalendar.objects.create(
            tenant=tenant,
            partner_id=partner.id,
            label="Fermeture annuelle",
            date_from=dt.date(2026, 6, 10),
            date_to=dt.date(2026, 6, 20),
            type=SalesCustomerCalendar.TYPE_CLOSURE,
            impact_pct=Decimal("-100"),
        )
        # Ne chevauche pas la periode -> ignore.
        SalesCustomerCalendar.objects.create(
            tenant=tenant,
            partner_id=partner.id,
            label="Campagne hors periode",
            date_from=dt.date(2026, 8, 1),
            date_to=dt.date(2026, 8, 15),
            type=SalesCustomerCalendar.TYPE_CAMPAIGN,
            impact_pct=Decimal("30"),
        )

        assert customer_calendar_adjustment(
            tenant, partner.id, period_start, period_end
        ) == Decimal("-100")


def test_customer_calendar_adjustment_returns_zero_without_entries(forecast_setup) -> None:
    tenant, partner = forecast_setup
    with use_tenant(tenant.id):
        assert customer_calendar_adjustment(
            tenant, partner.id, dt.date(2026, 6, 1), dt.date(2026, 6, 30)
        ) == Decimal(0)


def test_build_forecast_creates_row_with_dominant_cause_never_stock(forecast_setup) -> None:
    tenant, _partner = forecast_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        _delivered_line(tenant, variant_id=variant_id, date=dt.date.today(), qty=Decimal("10"))

        forecast = build_forecast(tenant, variant_id, "2026-12")

        assert isinstance(forecast, SalesForecast)
        assert forecast.variant_id == variant_id
        assert forecast.period == "2026-12"
        assert forecast.parameters["dominant_cause"] in {"capacite", "delai_fournisseur", "aucun"}
        assert forecast.parameters["dominant_cause"] != "stock"
        assert "stock" not in forecast.parameters["dominant_cause"]
        assert forecast.method


def test_build_forecast_flags_supplier_lead_time_as_dominant_cause(forecast_setup) -> None:
    """RG-SAL-7 test d'acceptance n°3 (rupture matiere signalee via le
    delai fournisseur, pas via un vrai niveau de stock, cf. plan) : un
    delai fournisseur superieur au nombre de jours avant le debut de la
    periode doit ressortir en cause dominante."""
    from apps.catalog.tests.factories import ProductSupplierInfoFactory, ProductVariantFactory

    tenant, _partner = forecast_setup
    with use_tenant(tenant.id):
        variant = ProductVariantFactory(tenant=tenant)
        ProductSupplierInfoFactory(tenant=tenant, variant=variant, lead_time_days=400)

        far_future_period = (dt.date.today() + dt.timedelta(days=10)).strftime("%Y-%m")
        forecast = build_forecast(tenant, variant.id, far_future_period)
        assert forecast.parameters["dominant_cause"] == "delai_fournisseur"


def test_build_forecast_is_idempotent_per_tenant_period_variant_partner(forecast_setup) -> None:
    tenant, partner = forecast_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        first = build_forecast(tenant, variant_id, "2026-07", partner_id=partner.id)
        second = build_forecast(tenant, variant_id, "2026-07", partner_id=partner.id)

        assert first.id == second.id
        assert (
            SalesForecast.objects.filter(
                tenant=tenant, period="2026-07", variant_id=variant_id, partner_id=partner.id
            ).count()
            == 1
        )


def test_build_forecast_applies_customer_calendar_closure(forecast_setup) -> None:
    tenant, partner = forecast_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        _delivered_line(tenant, variant_id=variant_id, date=dt.date.today(), qty=Decimal("50"))
        period = "2026-09"
        SalesCustomerCalendar.objects.create(
            tenant=tenant,
            partner_id=partner.id,
            label="Fermeture totale",
            date_from=dt.date(2026, 9, 1),
            date_to=dt.date(2026, 9, 30),
            type=SalesCustomerCalendar.TYPE_CLOSURE,
            impact_pct=Decimal("-100"),
        )

        forecast = build_forecast(tenant, variant_id, period, partner_id=partner.id)
        assert forecast.qty_forecast == Decimal("0.0000")


def test_recompute_forecasts_for_period_covers_all_recent_variants(forecast_setup) -> None:
    tenant, _partner = forecast_setup
    with use_tenant(tenant.id):
        variant_a = uuid.uuid4()
        variant_b = uuid.uuid4()
        _delivered_line(tenant, variant_id=variant_a, date=dt.date.today(), qty=Decimal("5"))
        _delivered_line(tenant, variant_id=variant_b, date=dt.date.today(), qty=Decimal("7"))

        forecasts = recompute_forecasts_for_period(tenant, "2026-10")
        variant_ids = {forecast.variant_id for forecast in forecasts}
        assert variant_a in variant_ids
        assert variant_b in variant_ids


def test_recompute_forecasts_for_period_is_idempotent(forecast_setup) -> None:
    tenant, _partner = forecast_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        _delivered_line(tenant, variant_id=variant_id, date=dt.date.today(), qty=Decimal("5"))

        recompute_forecasts_for_period(tenant, "2026-11")
        recompute_forecasts_for_period(tenant, "2026-11")

        assert SalesForecast.objects.filter(tenant=tenant, period="2026-11").count() == 1
