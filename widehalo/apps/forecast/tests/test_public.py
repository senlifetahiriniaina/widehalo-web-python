"""Contrat public de `forecast` (`services/public.py`) — FOR-10."""

from __future__ import annotations

import pytest
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.forecast.services.public import get_latest_published_forecast
from apps.forecast.services.publication import publish
from apps.forecast.tests.factories import ForSeriesForecastFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def public_tenant() -> Tenant:
    return Tenant.objects.create(code="FOR-PUB2", name="Forecast Public Tenant")


def test_get_latest_published_forecast_none_when_never_published(public_tenant: Tenant) -> None:
    with use_tenant(public_tenant.id):
        assert get_latest_published_forecast(public_tenant) is None


def test_get_latest_published_forecast_returns_primitives(public_tenant: Tenant) -> None:
    with use_tenant(public_tenant.id):
        ForSeriesForecastFactory(tenant=public_tenant)
        publish(public_tenant, user=None)

        result = get_latest_published_forecast(public_tenant)

    assert result["version"] == 1
    assert "snapshot" in result
    assert isinstance(result["snapshot"], list)
