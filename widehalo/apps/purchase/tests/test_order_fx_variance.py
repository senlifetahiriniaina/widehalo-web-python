"""B3 (Phase 3, ACH-6 : "taux de change commande d'achat exploité") :
`services/orders.py::order_fx_variance` — calque direct de
`apps.financing.tests.test_credoc_fx_variance` (patron déjà livré en B2
pour `financing.services.credoc.credoc_fx_variance`), adapté à la
différence structurelle de `PurOrder` : pas de champ montant en devise
étrangère stocké, le montant implicite est reconstruit à partir du taux
capturé par `create_order` (cf. docstring de `order_fx_variance`)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.accounting.models import AccExchangeRate
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.purchase.services.orders import add_order_line, create_order, order_fx_variance

pytestmark = pytest.mark.django_db


def test_order_fx_variance_is_none_for_mga_order() -> None:
    tenant = Tenant.objects.create(code="PUR-FX1", name="Purchase FX Tenant 1")
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date(2026, 1, 1))
        assert order_fx_variance(order) is None


def test_order_fx_variance_is_none_when_no_rate_was_ever_captured() -> None:
    """Garde spécifique à `PurOrder`, sans équivalent côté `FinCredoc` (cf.
    docstring de `order_fx_variance`) : une commande en devise étrangère
    dont la capture du taux a échoué faute d'`AccExchangeRate` configuré
    (`exchange_rate` resté à son défaut `1`) ne doit jamais produire un
    écart artefactuel."""
    tenant = Tenant.objects.create(code="PUR-FX2", name="Purchase FX Tenant 2")
    with use_tenant(tenant.id):
        order = create_order(
            tenant=tenant, partner_id=uuid.uuid4(), date=dt.date(2026, 1, 1), currency="EUR"
        )
        assert order.exchange_rate == Decimal(1)
        assert order_fx_variance(order) is None


def test_order_fx_variance_flags_material_gap() -> None:
    tenant = Tenant.objects.create(code="PUR-FX3", name="Purchase FX Tenant 3")
    with use_tenant(tenant.id):
        AccExchangeRate.objects.create(
            tenant=tenant, currency="EUR", date=dt.date(2026, 1, 1), rate_to_mga=Decimal("5000")
        )
        order = create_order(
            tenant=tenant, partner_id=uuid.uuid4(), date=dt.date(2026, 1, 1), currency="EUR"
        )
        add_order_line(
            order,
            variant_id=uuid.uuid4(),
            description="Tissu importé",
            qty=Decimal(6),
            unit_price_mga=Decimal(5000000),
        )
        order.refresh_from_db()
        assert order.amount_total_mga == Decimal("30000000.0000")

        AccExchangeRate.objects.create(
            tenant=tenant, currency="EUR", date=dt.date(2026, 2, 1), rate_to_mga=Decimal("5400")
        )
        result = order_fx_variance(order, as_of=dt.date(2026, 2, 1))
        assert result is not None
        assert result["booked_amount_mga"] == Decimal("30000000.0000")
        assert result["current_amount_mga"] == Decimal("32400000.0000")
        assert result["variance_mga"] == Decimal("2400000.0000")
        assert result["variance_pct"].quantize(Decimal("0.01")) == Decimal("8.00")
        assert result["is_material"] is True


def test_order_fx_variance_not_material_under_threshold() -> None:
    tenant = Tenant.objects.create(code="PUR-FX4", name="Purchase FX Tenant 4")
    with use_tenant(tenant.id):
        AccExchangeRate.objects.create(
            tenant=tenant, currency="EUR", date=dt.date(2026, 1, 1), rate_to_mga=Decimal("5000")
        )
        order = create_order(
            tenant=tenant, partner_id=uuid.uuid4(), date=dt.date(2026, 1, 1), currency="EUR"
        )
        add_order_line(
            order,
            variant_id=uuid.uuid4(),
            description="Tissu importé",
            qty=Decimal(6),
            unit_price_mga=Decimal(5000000),
        )
        order.refresh_from_db()

        AccExchangeRate.objects.create(
            tenant=tenant, currency="EUR", date=dt.date(2026, 2, 1), rate_to_mga=Decimal("5005")
        )
        result = order_fx_variance(order, as_of=dt.date(2026, 2, 1))
        assert result is not None
        assert result["is_material"] is False


def test_order_fx_variance_is_none_when_as_of_rate_unconfigured() -> None:
    """Taux réellement capturé au booking, mais aucun `AccExchangeRate`
    connu à `as_of` — branche `except ValidationError` propre à
    `order_fx_variance` (elle refait une résolution de taux à `as_of`,
    contrairement à `credoc_fx_variance` qui n'en fait qu'une seule)."""
    tenant = Tenant.objects.create(code="PUR-FX5", name="Purchase FX Tenant 5")
    with use_tenant(tenant.id):
        AccExchangeRate.objects.create(
            tenant=tenant, currency="EUR", date=dt.date(2026, 1, 1), rate_to_mga=Decimal("5000")
        )
        order = create_order(
            tenant=tenant, partner_id=uuid.uuid4(), date=dt.date(2026, 1, 1), currency="EUR"
        )
        assert order.exchange_rate != Decimal(1)

        assert order_fx_variance(order, as_of=dt.date(2020, 1, 1)) is None
