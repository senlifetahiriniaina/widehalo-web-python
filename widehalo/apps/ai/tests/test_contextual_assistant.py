"""AI2 : `apps.ai.services.contextual_assistant`. Verifie la garantie
"fallback-first" (jamais d'exception, module non enregistre OU provider
stub), le comportement de cache (300s, pas de second appel LLM tant que la
cle ne change pas) et la journalisation restreinte aux vrais appels LLM."""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.test import override_settings

from apps.ai.models import AiRequest
from apps.ai.services.contextual_assistant import assist
from apps.ai.tests.factories import AiUsageLimitFactory
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.ai_assistant import AIProviderError
from apps.core.services.ai_context_registry import register_context
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(code="AI-ASSIST", name="Tenant Assist")


@pytest.fixture
def user(tenant: Tenant) -> User:
    return User.objects.create_user(email="assist@example.com", password="Str0ngPassw0rd!23")


@pytest.fixture
def registered_module():
    register_context(
        "test_assist_module",
        static_guidance_fr="Guidance statique FR de test.",
        static_guidance_en="Static test guidance EN.",
    )
    return "test_assist_module"


def test_unregistered_module_returns_generic_fallback_never_raises(
    tenant: Tenant, user: User
) -> None:
    with use_tenant(tenant.id):
        response = assist(
            "module_qui_nexiste_pas", "consulter", tenant=tenant, user=user, locale="fr"
        )
    assert response["is_ai_generated"] is False
    assert response["guidance"]


@override_settings(AI_PROVIDER_CONFIG={})
def test_registered_module_without_real_provider_returns_static_guidance(
    tenant: Tenant, user: User, registered_module: str
) -> None:
    with use_tenant(tenant.id):
        response = assist(registered_module, "consulter", tenant=tenant, user=user, locale="fr")
    assert response["is_ai_generated"] is False
    assert response["guidance"] == "Guidance statique FR de test."


@override_settings(AI_PROVIDER_CONFIG={})
def test_locale_en_returns_english_static_guidance(
    tenant: Tenant, user: User, registered_module: str
) -> None:
    with use_tenant(tenant.id):
        response = assist(registered_module, "consulter", tenant=tenant, user=user, locale="en")
    assert response["guidance"] == "Static test guidance EN."


@override_settings(AI_PROVIDER_CONFIG={})
def test_static_fallback_path_does_not_log_ai_request(
    tenant: Tenant, user: User, registered_module: str
) -> None:
    with use_tenant(tenant.id):
        assist(registered_module, "consulter", tenant=tenant, user=user, locale="fr")
        assert AiRequest.objects.filter(tenant=tenant).count() == 0


def test_cache_hit_avoids_second_provider_call(
    tenant: Tenant, user: User, registered_module: str, monkeypatch
) -> None:
    call_count = {"n": 0}

    class _CountingProvider:
        def complete(self, prompt: str, *, max_tokens: int = 500) -> str:
            call_count["n"] += 1
            return "Reponse generee par le LLM."

    monkeypatch.setattr(
        "apps.ai.services.contextual_assistant.get_budget_gated_provider",
        lambda tenant: _CountingProvider(),
    )

    with use_tenant(tenant.id):
        first = assist(registered_module, "creer", tenant=tenant, user=user, locale="fr")
        second = assist(registered_module, "creer", tenant=tenant, user=user, locale="fr")
        # `AiRequest.objects` (TenantManager) est scope au tenant actif du
        # contexte courant — la lecture doit rester DANS le `with`.
        assert AiRequest.objects.filter(tenant=tenant).count() == 1

    assert call_count["n"] == 1
    assert first["is_ai_generated"] is True
    assert second == first


def test_ai_provider_error_falls_back_to_static_guidance_and_logs_failure(
    tenant: Tenant, user: User, registered_module: str, monkeypatch
) -> None:
    class _FailingProvider:
        def complete(self, prompt: str, *, max_tokens: int = 500) -> str:
            raise AIProviderError("panne reseau simulee")

    monkeypatch.setattr(
        "apps.ai.services.contextual_assistant.get_budget_gated_provider",
        lambda tenant: _FailingProvider(),
    )

    with use_tenant(tenant.id):
        response = assist(registered_module, "creer", tenant=tenant, user=user, locale="fr")
        request_row = AiRequest.objects.get(tenant=tenant)
        assert request_row.succeeded is False

    assert response["is_ai_generated"] is False
    assert response["guidance"] == "Guidance statique FR de test."


def test_over_budget_tenant_never_reaches_real_provider(
    tenant: Tenant, user: User, registered_module: str, monkeypatch
) -> None:
    """Meme discipline que `test_usage_budget.py` : un tenant au-dela de
    son budget (`hard_stop=True`) doit systematiquement recevoir la
    guidance statique, meme si un fournisseur reel est configure."""

    def _forbidden_provider(*args, **kwargs):
        raise AssertionError("get_ai_provider() ne doit jamais etre appele hors budget")

    monkeypatch.setattr("apps.ai.services.usage_budget.get_ai_provider", _forbidden_provider)
    with use_tenant(tenant.id):
        AiUsageLimitFactory(tenant=tenant, monthly_token_budget=1, hard_stop=True)
        from apps.ai.tests.factories import AiRequestFactory

        AiRequestFactory(tenant=tenant, prompt_tokens_estimate=1000, completion_tokens_estimate=0)

        response = assist(registered_module, "consulter", tenant=tenant, user=user, locale="fr")

    assert response["is_ai_generated"] is False
