"""AI5 : adaptateur `apps.sales.services.ai_insight_registration` —
verifie que la source REELLE lit correctement `seasonal_coefficient`/
`dominant_cause` deja calcules et persistes par `services.forecast.
build_forecast` (RG-SAL-7, S6) sur un `SalesForecast` reel, sans jamais
recalculer une nouvelle prevision."""

from __future__ import annotations

import pytest

from apps.core.models.tenant import Tenant
from apps.core.services.insight_source_registry import get_insight_source
from apps.core.tests.utils import use_tenant
from apps.sales.services.ai_insight_registration import _seasonal_demand_uptick
from apps.sales.tests.factories import SalesForecastFactory

pytestmark = pytest.mark.django_db


def test_source_is_registered_in_the_shared_registry() -> None:
    registered = get_insight_source("sales.seasonal_demand_uptick")
    assert registered is not None
    assert registered.module == "sales"
    assert registered.function is _seasonal_demand_uptick


def test_source_surfaces_a_future_forecast_with_a_seasonal_uptick() -> None:
    tenant = Tenant.objects.create(code="SALES-AI5-1", name="Sales AI5 Tenant 1")
    with use_tenant(tenant.id):
        forecast = SalesForecastFactory(
            tenant=tenant,
            period="2026-12",
            qty_forecast=50,
            parameters={"dominant_cause": "aucun", "seasonal_coefficient": "1.5"},
        )
        candidates = _seasonal_demand_uptick(str(tenant.id))

    assert len(candidates) == 1
    assert candidates[0].category == "ventes"
    assert candidates[0].source_modules == ["sales"]
    assert str(forecast.variant_id) in candidates[0].body
    assert "2026-12" in candidates[0].title
    assert "+50%" in candidates[0].body


def test_source_ignores_forecast_with_a_capacity_or_supplier_gap() -> None:
    tenant = Tenant.objects.create(code="SALES-AI5-2", name="Sales AI5 Tenant 2")
    with use_tenant(tenant.id):
        SalesForecastFactory(
            tenant=tenant,
            period="2026-12",
            qty_forecast=50,
            parameters={"dominant_cause": "capacite", "seasonal_coefficient": "1.5"},
        )
        candidates = _seasonal_demand_uptick(str(tenant.id))

    assert candidates == []


def test_source_ignores_forecast_below_the_uptick_threshold() -> None:
    tenant = Tenant.objects.create(code="SALES-AI5-3", name="Sales AI5 Tenant 3")
    with use_tenant(tenant.id):
        SalesForecastFactory(
            tenant=tenant,
            period="2026-12",
            qty_forecast=50,
            parameters={"dominant_cause": "aucun", "seasonal_coefficient": "1.05"},
        )
        candidates = _seasonal_demand_uptick(str(tenant.id))

    assert candidates == []


def test_source_ignores_a_past_period() -> None:
    tenant = Tenant.objects.create(code="SALES-AI5-4", name="Sales AI5 Tenant 4")
    with use_tenant(tenant.id):
        SalesForecastFactory(
            tenant=tenant,
            period="2020-01",
            qty_forecast=50,
            parameters={"dominant_cause": "aucun", "seasonal_coefficient": "1.5"},
        )
        candidates = _seasonal_demand_uptick(str(tenant.id))

    assert candidates == []
