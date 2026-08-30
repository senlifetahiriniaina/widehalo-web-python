"""AI3 : adaptateur `apps.sales.services.ai_anomaly_registration` —
verifie que le check REEL lit correctement `dominant_cause` deja calcule
et persiste par `services.forecast.build_forecast` (RG-SAL-7, S6) sur un
`SalesForecast` reel, sans jamais recalculer une nouvelle prevision."""

from __future__ import annotations

import pytest

from apps.core.models.tenant import Tenant
from apps.core.services.anomaly_registry import SEVERITY_HIGH, SEVERITY_MEDIUM, get_anomaly_check
from apps.core.tests.utils import use_tenant
from apps.sales.services.ai_anomaly_registration import _check_forecast_gap
from apps.sales.tests.factories import SalesForecastFactory

pytestmark = pytest.mark.django_db


def test_check_is_registered_in_the_shared_registry() -> None:
    registered = get_anomaly_check("sales.forecast_gap")
    assert registered is not None
    assert registered.module == "sales"
    assert registered.function is _check_forecast_gap


def test_check_surfaces_capacity_gap_as_high() -> None:
    tenant = Tenant.objects.create(code="SALES-AI3-1", name="Sales AI3 Tenant 1")
    with use_tenant(tenant.id):
        forecast = SalesForecastFactory(
            tenant=tenant,
            qty_forecast=50,
            parameters={"dominant_cause": "capacite"},
        )
        candidates = _check_forecast_gap(str(tenant.id))

    assert len(candidates) == 1
    assert candidates[0].content_type_label == "sales.salesforecast"
    assert candidates[0].object_id == str(forecast.id)
    assert candidates[0].severity == SEVERITY_HIGH


def test_check_surfaces_supplier_lead_time_gap_as_medium() -> None:
    tenant = Tenant.objects.create(code="SALES-AI3-2", name="Sales AI3 Tenant 2")
    with use_tenant(tenant.id):
        SalesForecastFactory(
            tenant=tenant,
            qty_forecast=20,
            parameters={"dominant_cause": "delai_fournisseur"},
        )
        candidates = _check_forecast_gap(str(tenant.id))

    assert len(candidates) == 1
    assert candidates[0].severity == SEVERITY_MEDIUM


def test_check_ignores_forecasts_without_a_dominant_cause() -> None:
    tenant = Tenant.objects.create(code="SALES-AI3-3", name="Sales AI3 Tenant 3")
    with use_tenant(tenant.id):
        SalesForecastFactory(tenant=tenant, qty_forecast=20, parameters={"dominant_cause": "aucun"})
        SalesForecastFactory(
            tenant=tenant, qty_forecast=0, parameters={"dominant_cause": "capacite"}
        )

        candidates = _check_forecast_gap(str(tenant.id))

    assert candidates == []
