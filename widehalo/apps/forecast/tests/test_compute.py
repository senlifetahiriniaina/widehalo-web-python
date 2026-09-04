"""Calcul et persistance des prévisions (`services/compute.py`)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from apps.analytics.tests.factories import AnDimTempsFactory, AnFactVenteFactory
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.forecast.models import ForSeriesForecast
from apps.forecast.services.compute import compute_and_store_forecast

pytestmark = pytest.mark.django_db


@pytest.fixture
def compute_tenant() -> Tenant:
    return Tenant.objects.create(code="FOR-COMP", name="Forecast Compute Tenant")


def _seed_months(tenant: Tenant, n: int, *, base_value: int = 1000) -> None:
    year, month = 2024, 1
    for i in range(n):
        dim_temps = AnDimTempsFactory(tenant=tenant, date=dt.date(year, month, 15))
        AnFactVenteFactory(
            tenant=tenant, dim_temps=dim_temps, montant_ht_mga=Decimal(base_value + i * 10)
        )
        month += 1
        if month > 12:
            month = 1
            year += 1


def test_compute_and_store_forecast_creates_rows_for_the_horizon(compute_tenant: Tenant) -> None:
    with use_tenant(compute_tenant.id):
        _seed_months(compute_tenant, 15)

        rows = compute_and_store_forecast(
            compute_tenant,
            dimension_type="canal",
            dimension_value="vente_directe",
            horizon_months=6,
        )

        assert len(rows) == 6
        stored = list(
            ForSeriesForecast.objects.filter(
                tenant=compute_tenant, dimension_type="canal", dimension_value="vente_directe"
            )
        )
        assert len(stored) == 6
        for row in stored:
            assert row.selected_model
            assert row.statistical_value is not None
            assert row.reference_naive_value is not None
            assert row.test_window_start <= row.test_window_end


def test_compute_and_store_forecast_is_idempotent_on_replay(compute_tenant: Tenant) -> None:
    with use_tenant(compute_tenant.id):
        _seed_months(compute_tenant, 15)

        compute_and_store_forecast(
            compute_tenant,
            dimension_type="canal",
            dimension_value="vente_directe",
            horizon_months=3,
        )
        compute_and_store_forecast(
            compute_tenant,
            dimension_type="canal",
            dimension_value="vente_directe",
            horizon_months=3,
        )

        assert (
            ForSeriesForecast.objects.filter(
                tenant=compute_tenant, dimension_type="canal", dimension_value="vente_directe"
            ).count()
            == 3
        )


def test_compute_and_store_forecast_returns_empty_when_no_history(compute_tenant: Tenant) -> None:
    with use_tenant(compute_tenant.id):
        rows = compute_and_store_forecast(
            compute_tenant, dimension_type="canal", dimension_value="pos", horizon_months=3
        )
        assert rows == []
