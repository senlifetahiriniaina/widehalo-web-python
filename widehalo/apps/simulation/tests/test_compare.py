"""Comparateur de scénarios (SIM-6) — `services.scenarios.compare_scenarios`."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.simulation.services.scenarios import compare_scenarios, create_scenario
from apps.simulation.tests.factories import SimBaselineFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant() -> Tenant:
    t = Tenant.objects.create(code="SIM-CMP", name="Simulation Compare Tenant")
    with use_tenant(t.id):
        yield t


def test_compare_scenarios_requires_between_two_and_four(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        baseline = SimBaselineFactory(tenant=tenant)
        owner = UserFactory()
        scenario = create_scenario(tenant, baseline=baseline, name="Seul", levers={}, owner=owner)

        with pytest.raises(ValidationError, match="SIM-6"):
            compare_scenarios(owner, [str(scenario.id)])


def test_compare_scenarios_returns_indicators_side_by_side(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        baseline = SimBaselineFactory(tenant=tenant)
        owner = UserFactory()
        scenario_a = create_scenario(
            tenant, baseline=baseline, name="A", levers={"prix_vente_pct": 5}, owner=owner
        )
        scenario_b = create_scenario(
            tenant, baseline=baseline, name="B", levers={"prix_vente_pct": -5}, owner=owner
        )

        rows = compare_scenarios(owner, [str(scenario_a.id), str(scenario_b.id)])

    assert [row["name"] for row in rows] == ["A", "B"]
    assert rows[0]["indicators"]["ca"] != rows[1]["indicators"]["ca"]


def test_compare_scenarios_rejects_a_scenario_not_owned_and_not_shared(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        baseline = SimBaselineFactory(tenant=tenant)
        owner = UserFactory()
        other = UserFactory()
        scenario_a = create_scenario(
            tenant, baseline=baseline, name="A", levers={}, owner=owner, is_shared=False
        )
        scenario_b = create_scenario(tenant, baseline=baseline, name="B", levers={}, owner=other)

        with pytest.raises(ValidationError):
            compare_scenarios(other, [str(scenario_a.id), str(scenario_b.id)])
