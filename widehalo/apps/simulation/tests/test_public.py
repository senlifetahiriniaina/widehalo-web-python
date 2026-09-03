"""Contrat public de `simulation` — `services.public.preview_indicators_
for_levers` (outil IA `simulation.propose_scenario`, SIM-8) et journal
d'audit de `services.scenarios.apply_ai_proposed_levers`."""

from __future__ import annotations

import pytest

from apps.core.models.audit import AuditLog
from apps.core.models.tenant import Tenant
from apps.core.services.data_query_tool_registry import list_data_query_tools
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.simulation.services.ai_data_query_registration import _tool_propose_scenario
from apps.simulation.services.public import (
    get_lever_catalog,
    get_scenario_summary,
    preview_indicators_for_levers,
)
from apps.simulation.services.scenarios import apply_ai_proposed_levers
from apps.simulation.tests.factories import SimBaselineFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant() -> Tenant:
    t = Tenant.objects.create(code="SIM-PUB", name="Simulation Public Tenant")
    with use_tenant(t.id):
        yield t


def test_preview_indicators_for_levers_returns_none_without_a_baseline(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        assert preview_indicators_for_levers(tenant, levers={}) is None


def test_preview_indicators_for_levers_computes_without_persisting_a_scenario(tenant: Tenant) -> None:
    from apps.simulation.models import SimScenario

    with use_tenant(tenant.id):
        SimBaselineFactory(tenant=tenant)

        result = preview_indicators_for_levers(tenant, levers={"prix_vente_pct": 10})

        assert result is not None
        assert result["indicators"]["ca"] == "110000000"
        assert SimScenario.objects.count() == 0


def test_get_lever_catalog_lists_every_family() -> None:
    catalog = get_lever_catalog()
    families = {row["family"] for row in catalog}
    assert families == {"commercial", "achats", "structure", "tresorerie", "fiscal"}


def test_get_scenario_summary_returns_none_for_an_archived_scenario(tenant: Tenant) -> None:
    from apps.simulation.services.scenarios import archive_scenario, create_scenario

    with use_tenant(tenant.id):
        baseline = SimBaselineFactory(tenant=tenant)
        owner = UserFactory()
        scenario = create_scenario(tenant, baseline=baseline, name="X", levers={}, owner=owner)
        archive_scenario(scenario, user=owner)

        assert get_scenario_summary(scenario.id) is None


def test_ai_tool_propose_scenario_is_registered_read_only() -> None:
    tools = list_data_query_tools()
    tool = next(t for t in tools if t.code == "simulation.propose_scenario")
    assert tool.required_permission == "simulation.view_simscenario"
    assert tool.function is _tool_propose_scenario


def test_ai_tool_propose_scenario_never_creates_a_scenario(tenant: Tenant) -> None:
    from apps.simulation.models import SimScenario

    with use_tenant(tenant.id):
        SimBaselineFactory(tenant=tenant)
        owner = UserFactory()

        result = _tool_propose_scenario(tenant, owner, prix_vente_pct=10)

        assert result["indicators"]["ca"] == "110000000"
        assert SimScenario.objects.count() == 0


def test_apply_ai_proposed_levers_persists_a_scenario_and_logs_the_request(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        baseline = SimBaselineFactory(tenant=tenant)
        owner = UserFactory()

        scenario = apply_ai_proposed_levers(
            tenant,
            baseline=baseline,
            nl_request="Et si on baissait les prix de 5 % ?",
            proposed_levers={"prix_vente_pct": -5},
            owner=owner,
        )

        assert scenario.ai_generated is True
        assert scenario.ai_request_text == "Et si on baissait les prix de 5 % ?"

        log = AuditLog.objects.filter(action="simulation.ai_scenario_applied").latest("created_at")
        assert log.metadata["nl_request"] == "Et si on baissait les prix de 5 % ?"
        assert log.metadata["levers_applied"]["prix_vente_pct"] == "-5"
