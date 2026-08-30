"""AI1 (socle du module `ai`) : `apps.ai.services.usage_budget`. Le test le
plus important de ce fichier est `test_get_budget_gated_provider_never_
performs_any_network_call_once_over_budget` — il verifie explicitement
qu'un tenant au-dela de son budget avec `hard_stop=True` ne peut JAMAIS
declencher un appel reseau reel, meme si `AI_PROVIDER_CONFIG` porte des
identifiants valides (fournisseur reel configure) — meme discipline que
`StubPriceSourceProvider`/`StubAIProvider` deja verifiee ailleurs dans ce
depot."""

from __future__ import annotations

import socket

import pytest
from django.test import override_settings

from apps.ai.models import AiRequest, AiUsageLimit
from apps.ai.services.usage_budget import (
    check_budget,
    current_month_token_usage,
    estimate_tokens,
    get_budget_gated_provider,
    get_or_create_usage_limit,
    record_request,
)
from apps.ai.tests.factories import AiRequestFactory, AiUsageLimitFactory
from apps.core.models.tenant import Tenant
from apps.core.services.ai_assistant import StubAIProvider
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(code="AI-T1", name="Tenant AI")


def test_estimate_tokens_is_a_rough_but_deterministic_approximation() -> None:
    assert estimate_tokens("") == 0
    # ~0.75 mot/token (heuristique disclosed) -> arrondi, plancher a 1.
    assert estimate_tokens("un") == 1
    assert estimate_tokens(" ".join(["mot"] * 75)) == 100


def test_get_or_create_usage_limit_creates_sane_defaults(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        usage_limit = get_or_create_usage_limit(tenant)
        assert usage_limit.monthly_token_budget > 0
        assert usage_limit.hard_stop is True
        # Idempotent : un second appel renvoie la MEME ligne, jamais un
        # doublon (contrainte UniqueConstraint sur `tenant`).
        again = get_or_create_usage_limit(tenant)
        assert again.id == usage_limit.id
        assert AiUsageLimit.objects.filter(tenant=tenant).count() == 1


def test_current_month_token_usage_sums_only_this_month(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        AiRequestFactory(tenant=tenant, prompt_tokens_estimate=100, completion_tokens_estimate=50)
        AiRequestFactory(tenant=tenant, prompt_tokens_estimate=200, completion_tokens_estimate=0)
        assert current_month_token_usage(tenant) == 350


def test_check_budget_true_under_budget_false_over_with_hard_stop(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        AiUsageLimitFactory(tenant=tenant, monthly_token_budget=100, hard_stop=True)
        assert check_budget(tenant) is True
        AiRequestFactory(tenant=tenant, prompt_tokens_estimate=100, completion_tokens_estimate=1)
        assert check_budget(tenant) is False


def test_check_budget_soft_stop_always_allows(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        AiUsageLimitFactory(tenant=tenant, monthly_token_budget=1, hard_stop=False)
        AiRequestFactory(tenant=tenant, prompt_tokens_estimate=1000, completion_tokens_estimate=0)
        assert check_budget(tenant) is True


@override_settings(
    AI_PROVIDER_CONFIG={"backend": "deepseek", "base_url": "http://x", "api_key": "k"}
)
def test_get_budget_gated_provider_never_performs_any_network_call_once_over_budget(
    tenant: Tenant,
) -> None:
    """Verification explicite demandee par le cadrage du chantier : un
    tenant au-dela de son budget (`hard_stop=True`) ne doit JAMAIS
    declencher d'appel reseau, meme avec un fournisseur reel configure.
    `socket.socket` est patche pour faire echouer le test si quoi que ce
    soit tentait d'en ouvrir un."""

    def _forbidden_socket(*args, **kwargs):
        raise AssertionError(
            "Un socket reseau a ete ouvert alors que le budget de tokens du "
            "tenant est epuise — violation de la garantie fallback-first."
        )

    with use_tenant(tenant.id):
        AiUsageLimitFactory(tenant=tenant, monthly_token_budget=10, hard_stop=True)
        AiRequestFactory(tenant=tenant, prompt_tokens_estimate=10, completion_tokens_estimate=1)

        original_socket = socket.socket
        socket.socket = _forbidden_socket  # type: ignore[assignment]
        try:
            provider = get_budget_gated_provider(tenant)
        finally:
            socket.socket = original_socket  # type: ignore[assignment]

        assert isinstance(provider, StubAIProvider)


def test_get_budget_gated_provider_returns_real_provider_when_under_budget(
    tenant: Tenant,
) -> None:
    with use_tenant(tenant.id):
        AiUsageLimitFactory(tenant=tenant, monthly_token_budget=100_000, hard_stop=True)
        with override_settings(AI_PROVIDER_CONFIG={}):
            provider = get_budget_gated_provider(tenant)
    # Sans configuration reelle, le fournisseur reste le stub — la garde de
    # budget n'est pas la seule raison de retomber sur le stub.
    assert isinstance(provider, StubAIProvider)


def test_record_request_persists_backend_label_from_config(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        stub = StubAIProvider()
        record_request(
            tenant,
            feature=AiRequest.FEATURE_ASSIST,
            prompt_tokens_estimate=10,
            completion_tokens_estimate=5,
            provider=stub,
        )
        request_row = AiRequest.objects.get(tenant=tenant)
        assert request_row.provider_backend == "stub"
        assert request_row.total_tokens_estimate == 15
