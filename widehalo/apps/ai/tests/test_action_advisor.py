"""AI7 : `apps.ai.services.action_advisor`. Ne re-teste PAS les registres
eux-memes (deja couverts par `apps.core.tests.test_advisor_rule_registry`/
`test_automation_registry`) — se concentre sur `suggest` : persistance des
`RecommendationCandidate` (regles + automation_registry), isolation des
echecs, et le plafond de 3 recommandations par contexte.

**Isolation des registres (autouse fixture)** : meme raisonnement exact
que `apps.ai.tests.test_automated_insights` — les registres
`core.services.advisor_rule_registry._REGISTRY`/`automation_registry.
_REGISTRY` sont des dicts GLOBAUX au processus."""

from __future__ import annotations

import pytest

from apps.ai.models import AiRecommendation
from apps.ai.services.action_advisor import suggest
from apps.core.models.tenant import Tenant
from apps.core.services.advisor_rule_registry import RecommendationCandidate, register_advisor_rule
from apps.core.services.automation_registry import register_action
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _isolated_registries(monkeypatch):
    import apps.core.services.advisor_rule_registry as advisor_registry_module
    import apps.core.services.automation_registry as automation_registry_module

    monkeypatch.setattr(advisor_registry_module, "_REGISTRY", {})
    monkeypatch.setattr(automation_registry_module, "_REGISTRY", {})


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(code="AI7-ADV", name="Tenant AI7")


def test_suggest_persists_a_candidate_from_a_registered_rule(tenant: Tenant) -> None:
    def _rule(tenant_id: str, action: str, role_code: str) -> list[RecommendationCandidate]:
        return [RecommendationCandidate(label="Faites X", target_module="test")]

    register_advisor_rule("test.rule", module="test", label="Rule", function=_rule)

    with use_tenant(tenant.id):
        created = suggest("test", "consulter", tenant=tenant, role_code="admin")
        recommendation = AiRecommendation.objects.get(id=created[0].id)

    assert len(created) == 1
    assert recommendation.context_module == "test"
    assert recommendation.context_action == "consulter"
    assert recommendation.role_code == "admin"
    assert recommendation.label == "Faites X"
    assert recommendation.target_module == "test"
    assert recommendation.target_action_code == ""


def test_suggest_ignores_rules_from_other_modules(tenant: Tenant) -> None:
    def _rule(tenant_id: str, action: str, role_code: str) -> list[RecommendationCandidate]:
        return [RecommendationCandidate(label="Non pertinent", target_module="other")]

    register_advisor_rule("test.other_module", module="other", label="Rule", function=_rule)

    with use_tenant(tenant.id):
        created = suggest("test", "consulter", tenant=tenant, role_code="admin")

    assert created == []


def test_suggest_isolates_a_failing_rule_from_the_others(tenant: Tenant) -> None:
    def _failing_rule(tenant_id: str, action: str, role_code: str) -> list[RecommendationCandidate]:
        raise RuntimeError("bug dans l'adaptateur d'un module")

    def _working_rule(tenant_id: str, action: str, role_code: str) -> list[RecommendationCandidate]:
        return [RecommendationCandidate(label="Toujours genere", target_module="test")]

    register_advisor_rule(
        "test.isolation_failing", module="test", label="Failing", function=_failing_rule
    )
    register_advisor_rule(
        "test.isolation_working", module="test", label="Working", function=_working_rule
    )

    with use_tenant(tenant.id):
        created = suggest("test", "consulter", tenant=tenant, role_code="admin")

    assert len(created) == 1
    assert created[0].label == "Toujours genere"


def test_suggest_includes_a_candidate_from_automation_registry(tenant: Tenant) -> None:
    def _action(tenant_id: str, params: dict) -> None:
        return None

    register_action(code="test.do_thing", module="test", label="Faire un truc", function=_action)

    with use_tenant(tenant.id):
        created = suggest("test", "consulter", tenant=tenant, role_code="admin")

    assert len(created) == 1
    assert created[0].target_module == "test"
    assert created[0].target_action_code == "test.do_thing"
    assert "Faire un truc" in created[0].label


def test_suggest_returns_empty_list_when_no_candidate_matches(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        created = suggest("unmatched_module", "consulter", tenant=tenant, role_code="admin")

    assert created == []


def test_suggest_caps_recommendations_at_three(tenant: Tenant) -> None:
    def _rule(tenant_id: str, action: str, role_code: str) -> list[RecommendationCandidate]:
        return [
            RecommendationCandidate(label="Un", target_module="test"),
            RecommendationCandidate(label="Deux", target_module="test"),
        ]

    register_advisor_rule("test.multi", module="test", label="Multi", function=_rule)

    def _action_a(tenant_id: str, params: dict) -> None:
        return None

    def _action_b(tenant_id: str, params: dict) -> None:
        return None

    register_action(code="test.action_a", module="test", label="A", function=_action_a)
    register_action(code="test.action_b", module="test", label="B", function=_action_b)

    with use_tenant(tenant.id):
        created = suggest("test", "consulter", tenant=tenant, role_code="admin")

    assert len(created) == 3
