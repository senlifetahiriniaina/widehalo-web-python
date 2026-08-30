"""AI5 : `apps.ai.services.automated_insights`. Ne re-teste PAS le registre
lui-meme (deja couvert par `apps.core.tests.test_insight_source_registry`)
— se concentre sur `generate` : persistance des `InsightCandidate`,
isolation des echecs, synthese cross-module optionnelle (2+ modules ET
provider reel ET succes), et notification `direction`.

**Isolation du registre (autouse fixture `_isolated_registry`)** : meme
raisonnement exact que `apps.ai.tests.test_anomaly_detection` — le
registre `core.services.insight_source_registry._REGISTRY` est un dict
GLOBAL au processus."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group
from django.test import override_settings

from apps.ai.models import AiInsight
from apps.ai.services.automated_insights import generate
from apps.core.models.notification import Notification
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.services.insight_source_registry import InsightCandidate, register_insight_source
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch):
    import apps.core.services.insight_source_registry as registry_module

    monkeypatch.setattr(registry_module, "_REGISTRY", {})


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(code="AI5-INS", name="Tenant AI5")


def _direction_user(tenant: Tenant) -> User:
    user = User.objects.create_user(email="direction-ai5@example.com", password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name="direction")
    user.groups.add(group)
    UserTenantMembership.objects.create(user=user, tenant=tenant)
    return user


@override_settings(AI_PROVIDER_CONFIG={})
def test_generate_persists_candidates_from_a_registered_source(tenant: Tenant) -> None:
    def _source(tenant_id: str) -> list[InsightCandidate]:
        return [
            InsightCandidate(
                category="ventes",
                title="Titre de test",
                body="Corps de test.",
                source_modules=["sales"],
            )
        ]

    register_insight_source("test.persist", module="test", label="Persist", function=_source)
    _direction_user(tenant)

    with use_tenant(tenant.id):
        created = generate(tenant)
        insight = AiInsight.objects.get(id=created[0].id)

    assert len(created) == 1
    assert insight.category == "ventes"
    assert insight.title == "Titre de test"
    assert insight.body == "Corps de test."
    assert insight.source_modules == ["sales"]
    assert insight.is_ai_generated is False


@override_settings(AI_PROVIDER_CONFIG={})
def test_generate_isolates_a_failing_source_from_the_others(tenant: Tenant) -> None:
    def _failing_source(tenant_id: str) -> list[InsightCandidate]:
        raise RuntimeError("bug dans l'adaptateur d'un module")

    def _working_source(tenant_id: str) -> list[InsightCandidate]:
        return [
            InsightCandidate(
                category="rh",
                title="Toujours genere",
                body="Malgre l'echec de l'autre source.",
                source_modules=["presence"],
            )
        ]

    register_insight_source(
        "test.isolation_failing", module="test", label="Failing", function=_failing_source
    )
    register_insight_source(
        "test.isolation_working", module="test", label="Working", function=_working_source
    )

    with use_tenant(tenant.id):
        created = generate(tenant)

    assert len(created) == 1
    assert created[0].title == "Toujours genere"


@override_settings(AI_PROVIDER_CONFIG={})
def test_no_synthesis_without_a_real_provider(tenant: Tenant) -> None:
    """Politique disclosed : synthese cross-module generee UNIQUEMENT si un
    provider reel est configure/disponible. `AI_PROVIDER_CONFIG={}` ->
    `StubAIProvider` -> aucun insight de synthese, meme avec 2+ modules
    contributeurs."""

    def _source_a(tenant_id: str) -> list[InsightCandidate]:
        return [InsightCandidate(category="ventes", title="A", body="A", source_modules=["sales"])]

    def _source_b(tenant_id: str) -> list[InsightCandidate]:
        return [InsightCandidate(category="rh", title="B", body="B", source_modules=["presence"])]

    register_insight_source("test.a", module="sales", label="A", function=_source_a)
    register_insight_source("test.b", module="presence", label="B", function=_source_b)

    with use_tenant(tenant.id):
        created = generate(tenant)

    assert len(created) == 2
    assert all(not insight.is_ai_generated for insight in created)
    assert not AiInsight.objects.filter(category="synthese").exists()


def test_no_synthesis_with_fewer_than_two_contributing_modules(tenant: Tenant, monkeypatch) -> None:
    """Meme avec un provider reel disponible, un seul module contributeur
    ne declenche jamais de synthese (bornage explicite du plan)."""

    class _CountingProvider:
        calls = 0

        def complete(self, prompt: str, *, max_tokens: int = 500) -> str:
            type(self).calls += 1
            return "Synthese generee."

    monkeypatch.setattr(
        "apps.ai.services.automated_insights.get_budget_gated_provider",
        lambda tenant: _CountingProvider(),
    )

    def _source_a(tenant_id: str) -> list[InsightCandidate]:
        return [InsightCandidate(category="ventes", title="A", body="A", source_modules=["sales"])]

    register_insight_source("test.single_module", module="sales", label="A", function=_source_a)

    with use_tenant(tenant.id):
        created = generate(tenant)

    assert len(created) == 1
    assert _CountingProvider.calls == 0
    assert not AiInsight.objects.filter(category="synthese").exists()


def test_synthesis_generated_with_two_modules_and_a_real_provider(
    tenant: Tenant, monkeypatch
) -> None:
    class _StubProvider:
        def complete(self, prompt: str, *, max_tokens: int = 500) -> str:
            assert "ventes" in prompt
            assert "rh" in prompt
            return "Observation qualitative reliant les deux modules."

    monkeypatch.setattr(
        "apps.ai.services.automated_insights.get_budget_gated_provider",
        lambda tenant: _StubProvider(),
    )

    def _source_a(tenant_id: str) -> list[InsightCandidate]:
        return [InsightCandidate(category="ventes", title="A", body="A", source_modules=["sales"])]

    def _source_b(tenant_id: str) -> list[InsightCandidate]:
        return [InsightCandidate(category="rh", title="B", body="B", source_modules=["presence"])]

    register_insight_source("test.synth_a", module="sales", label="A", function=_source_a)
    register_insight_source("test.synth_b", module="presence", label="B", function=_source_b)

    with use_tenant(tenant.id):
        created = generate(tenant)

    assert len(created) == 3
    synthesis = next(insight for insight in created if insight.category == "synthese")
    assert synthesis.is_ai_generated is True
    assert synthesis.body == "Observation qualitative reliant les deux modules."
    assert sorted(synthesis.source_modules) == ["presence", "sales"]


def test_synthesis_failure_never_blocks_deterministic_insights(tenant: Tenant, monkeypatch) -> None:
    from apps.core.services.ai_assistant import AIProviderError

    class _FailingProvider:
        def complete(self, prompt: str, *, max_tokens: int = 500) -> str:
            raise AIProviderError("panne reseau simulee")

    monkeypatch.setattr(
        "apps.ai.services.automated_insights.get_budget_gated_provider",
        lambda tenant: _FailingProvider(),
    )

    def _source_a(tenant_id: str) -> list[InsightCandidate]:
        return [InsightCandidate(category="ventes", title="A", body="A", source_modules=["sales"])]

    def _source_b(tenant_id: str) -> list[InsightCandidate]:
        return [InsightCandidate(category="rh", title="B", body="B", source_modules=["presence"])]

    register_insight_source("test.fail_a", module="sales", label="A", function=_source_a)
    register_insight_source("test.fail_b", module="presence", label="B", function=_source_b)

    with use_tenant(tenant.id):
        created = generate(tenant)

    assert len(created) == 2
    assert not AiInsight.objects.filter(category="synthese").exists()


@override_settings(AI_PROVIDER_CONFIG={})
def test_generate_notifies_direction_role_once_per_run(tenant: Tenant) -> None:
    user = _direction_user(tenant)

    def _source_a(tenant_id: str) -> list[InsightCandidate]:
        return [InsightCandidate(category="ventes", title="A", body="A", source_modules=["sales"])]

    def _source_b(tenant_id: str) -> list[InsightCandidate]:
        return [InsightCandidate(category="rh", title="B", body="B", source_modules=["presence"])]

    register_insight_source("test.notify_a", module="sales", label="A", function=_source_a)
    register_insight_source("test.notify_b", module="presence", label="B", function=_source_b)

    with use_tenant(tenant.id):
        generate(tenant)

    notifications = Notification.objects.filter(user=user, notification_type="ai.insight_generated")
    assert notifications.count() == 1
    assert notifications.first().payload["insight_count"] == 2


@override_settings(AI_PROVIDER_CONFIG={})
def test_generate_notifies_nothing_when_no_insight_is_produced(tenant: Tenant) -> None:
    user = _direction_user(tenant)

    with use_tenant(tenant.id):
        created = generate(tenant)

    assert created == []
    assert not Notification.objects.filter(user=user).exists()
