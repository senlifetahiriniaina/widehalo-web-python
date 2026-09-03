"""Contrat public de `analytics` (`services/public.py`) — surface consommée
par le futur module BI (Phase 2 §13.1)."""

from __future__ import annotations

import pytest

from apps.analytics.models import AnMetricDefinition
from apps.analytics.services.public import (
    get_metric_definition,
    get_warehouse_state,
    list_published_metrics,
)
from apps.analytics.tests.factories import AnMetricDefinitionFactory, AnWarehouseStateFactory
from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import grant_role, use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def public_tenant() -> Tenant:
    return Tenant.objects.create(code="AN-PUB", name="Analytics Public Tenant")


def test_get_warehouse_state_none_when_never_refreshed(public_tenant: Tenant) -> None:
    with use_tenant(public_tenant.id):
        assert get_warehouse_state(public_tenant) is None


def test_get_warehouse_state_reflects_lock(public_tenant: Tenant) -> None:
    with use_tenant(public_tenant.id):
        AnWarehouseStateFactory(tenant=public_tenant, is_locked=True)
        state = get_warehouse_state(public_tenant)
    assert state == {"is_locked": True, "last_successful_refresh_at": None}


def test_list_published_metrics_returns_primitives(public_tenant: Tenant) -> None:
    with use_tenant(public_tenant.id):
        AnMetricDefinitionFactory(
            tenant=public_tenant,
            code="ca.mensuel",
            libelle="CA mensuel",
            statut=AnMetricDefinition.STATUT_PUBLIE,
        )
        user = UserFactory()
        grant_role(user, "direction")
        results = list_published_metrics(public_tenant, user)
    assert results == [
        {
            "code": "ca.mensuel",
            "libelle": "CA mensuel",
            "unite": "",
            "module_source": "sales",
            "axes_autorises": [],
            "maille_minimale": "",
        }
    ]


def test_get_metric_definition_returns_none_when_absent(public_tenant: Tenant) -> None:
    with use_tenant(public_tenant.id):
        assert get_metric_definition(public_tenant, "does.not.exist") is None
