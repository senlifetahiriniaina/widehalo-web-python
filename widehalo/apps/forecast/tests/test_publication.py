"""Publication (`services/publication.py`) — cahier Phase 2 §13.2,
FOR-10 : prévision publiée disponible avec version et date."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.forecast.models import ForPublication
from apps.forecast.services.publication import get_latest_publication, publish
from apps.forecast.tests.factories import ForSeriesForecastFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def publication_tenant() -> Tenant:
    return Tenant.objects.create(code="FOR-PUB", name="Forecast Publication Tenant")


def test_publish_snapshots_current_forecasts_and_versions_sequentially(publication_tenant: Tenant) -> None:
    with use_tenant(publication_tenant.id):
        ForSeriesForecastFactory(
            tenant=publication_tenant, statistical_value=Decimal("1000"), adjusted_value=None
        )
        user = UserFactory()

        first = publish(publication_tenant, user=user)
        second = publish(publication_tenant, user=user)

        assert first.version == 1
        assert second.version == 2
        assert len(first.snapshot) == 1
        assert Decimal(first.snapshot[0]["value"]) == Decimal("1000")
        assert ForPublication.objects.filter(tenant=publication_tenant).count() == 2


def test_publish_uses_adjusted_value_when_present(publication_tenant: Tenant) -> None:
    with use_tenant(publication_tenant.id):
        ForSeriesForecastFactory(
            tenant=publication_tenant, statistical_value=Decimal("1000"), adjusted_value=Decimal("1200")
        )

        publication = publish(publication_tenant, user=None)

        assert Decimal(publication.snapshot[0]["value"]) == Decimal("1200")


def test_get_latest_publication_returns_the_highest_version(publication_tenant: Tenant) -> None:
    with use_tenant(publication_tenant.id):
        assert get_latest_publication(publication_tenant) is None
        ForSeriesForecastFactory(tenant=publication_tenant)
        publish(publication_tenant, user=None)
        latest = publish(publication_tenant, user=None)

        assert get_latest_publication(publication_tenant).version == latest.version == 2
