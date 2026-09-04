"""Cycle de vie d'un `SimScenario` — création/mise à jour avec le
garde-fou de tolérance SIM-4, archivage, scope SIM-9 (`services.scoping`)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.simulation.services.baseline import deserialize_baseline_data
from apps.simulation.services.engine import compute_indicators
from apps.simulation.services.scenarios import (
    archive_scenario,
    create_scenario,
    list_scenarios,
    update_scenario,
)
from apps.simulation.tests.factories import SimBaselineFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant() -> Tenant:
    t = Tenant.objects.create(code="SIM-SCN", name="Simulation Scenarios Tenant")
    with use_tenant(t.id):
        yield t


def test_create_scenario_persists_server_authoritative_indicators(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        baseline = SimBaselineFactory(tenant=tenant)
        owner = UserFactory()

        scenario = create_scenario(
            tenant,
            baseline=baseline,
            name="Hausse des prix",
            levers={"prix_vente_pct": 10},
            owner=owner,
        )

        assert scenario.computed_indicators["ca"] == "110000000"
        assert scenario.baseline_extracted_at == baseline.extracted_at
        assert scenario.baseline_regulatory_param_version == baseline.regulatory_param_version


def test_create_scenario_accepts_a_matching_client_computation(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        baseline = SimBaselineFactory(tenant=tenant)
        owner = UserFactory()
        baseline_data = deserialize_baseline_data(baseline)
        levers = {"prix_vente_pct": Decimal(5)}
        server_indicators = compute_indicators(baseline_data, levers)
        client_indicators = _to_float_tree(server_indicators)

        scenario = create_scenario(
            tenant,
            baseline=baseline,
            name="Scénario cohérent",
            levers=levers,
            owner=owner,
            client_computed_indicators=client_indicators,
        )

    assert scenario.id is not None


def test_create_scenario_rejects_a_diverging_client_computation(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        baseline = SimBaselineFactory(tenant=tenant)
        owner = UserFactory()

        with pytest.raises(ValidationError, match="SIM-4"):
            create_scenario(
                tenant,
                baseline=baseline,
                name="Scénario divergent",
                levers={"prix_vente_pct": 10},
                owner=owner,
                client_computed_indicators={"ca": 999999999},
            )


def test_update_scenario_by_a_non_owner_raises_permission_denied(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        baseline = SimBaselineFactory(tenant=tenant)
        owner = UserFactory()
        other = UserFactory()
        scenario = create_scenario(
            tenant, baseline=baseline, name="Scénario", levers={}, owner=owner
        )

        with pytest.raises(PermissionDenied):
            update_scenario(scenario, levers={"prix_vente_pct": 5}, user=other)


def test_update_scenario_by_the_owner_recomputes_indicators(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        baseline = SimBaselineFactory(tenant=tenant)
        owner = UserFactory()
        scenario = create_scenario(
            tenant, baseline=baseline, name="Scénario", levers={}, owner=owner
        )

        updated = update_scenario(scenario, levers={"volume_pct": 10}, user=owner)

        assert updated.computed_indicators["ca"] == "110000000"


def test_archive_scenario_soft_deletes_it(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        baseline = SimBaselineFactory(tenant=tenant)
        owner = UserFactory()
        scenario = create_scenario(
            tenant, baseline=baseline, name="A archiver", levers={}, owner=owner
        )

        archive_scenario(scenario, user=owner)
        scenario.refresh_from_db()

    assert scenario.is_active is False


def test_list_scenarios_hides_private_scenarios_of_other_users(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        baseline = SimBaselineFactory(tenant=tenant)
        owner = UserFactory()
        other = UserFactory()
        create_scenario(
            tenant, baseline=baseline, name="Privé", levers={}, owner=owner, is_shared=False
        )
        create_scenario(
            tenant, baseline=baseline, name="Partagé", levers={}, owner=owner, is_shared=True
        )

        visible_to_other = list(list_scenarios(tenant, other))

    names = {s.name for s in visible_to_other}
    assert names == {"Partagé"}


def test_list_scenarios_shows_own_private_scenarios(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        baseline = SimBaselineFactory(tenant=tenant)
        owner = UserFactory()
        create_scenario(
            tenant, baseline=baseline, name="Privé", levers={}, owner=owner, is_shared=False
        )

        visible = list(list_scenarios(tenant, owner))

    assert [s.name for s in visible] == ["Privé"]


def _to_float_tree(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _to_float_tree(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_to_float_tree(val) for val in value]
    return value
