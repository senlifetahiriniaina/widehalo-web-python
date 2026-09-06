"""AI1 (socle) : budget de tokens par tenant + point d'entree unique
« fallback-first » — cf. plan section « Module `ai` ». **Toute fonction IA
future de ce depot (AI2-AI7) doit obtenir son fournisseur via
`get_budget_gated_provider()` ci-dessous, jamais directement via
`apps.core.services.ai_assistant.get_ai_provider()`** : c'est ce wrapper
qui applique la garantie « au-dela du budget, bascule silencieuse sur le
fournisseur de repli, jamais un appel reseau facture en plus »."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from django.conf import settings
from django.db.models import Sum

from apps.ai.models import DEFAULT_ALERT_THRESHOLD_PCT, AiRequest, AiUsageLimit
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.ai_assistant import AIProvider, StubAIProvider, get_ai_provider

# Approximation grossiere du nombre de tokens a partir d'un texte — aucun
# tokenizer exact du fournisseur cible (DeepSeek/Kimi/local) n'est
# disponible sans dependance supplementaire. ~0.75 mot par token est une
# heuristique courante pour l'anglais/le francais, disclosed comme non-
# exacte : suffisante pour un suivi de budget indicatif, jamais une
# facturation au centime pres.
_WORDS_PER_TOKEN = 0.75

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    word_count = len(text.split())
    return max(1, round(word_count / _WORDS_PER_TOKEN))


def get_or_create_usage_limit(tenant: Tenant) -> AiUsageLimit:
    """Cree une configuration par defaut si le tenant n'en a encore aucune
    — l'absence de configuration ne doit jamais bloquer l'utilisateur ni
    autoriser une consommation illimitee."""
    usage_limit, _created = AiUsageLimit.objects.get_or_create(tenant=tenant)
    return usage_limit


def _current_month_bounds() -> tuple[datetime, datetime]:
    now = datetime.now(tz=UTC)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, now


def current_month_token_usage(tenant: Tenant) -> int:
    start, end = _current_month_bounds()
    aggregate = AiRequest.objects.filter(
        tenant=tenant, created_at__gte=start, created_at__lte=end
    ).aggregate(
        prompt=Sum("prompt_tokens_estimate"),
        completion=Sum("completion_tokens_estimate"),
    )
    return (aggregate["prompt"] or 0) + (aggregate["completion"] or 0)


def check_budget(tenant: Tenant) -> bool:
    """`True` si un appel reel au fournisseur IA est encore autorise ce
    mois-ci pour ce tenant. Ne fait JAMAIS d'appel reseau — une simple
    lecture/agregation locale."""
    usage_limit = get_or_create_usage_limit(tenant)
    if not usage_limit.hard_stop:
        return True
    return current_month_token_usage(tenant) < usage_limit.monthly_token_budget


def _resolve_backend_label(provider: AIProvider) -> str:
    if isinstance(provider, StubAIProvider):
        return "stub"
    # `AI_PROVIDER_CONFIG["backend"]` est une cle purement informative
    # (jamais lue par `get_ai_provider()` lui-meme, cf. sa docstring) —
    # elle sert ICI uniquement a peupler `AiRequest.provider_backend` a des
    # fins de diagnostic/cout, jamais a decider quel connecteur instancier.
    config: dict[str, str] = getattr(settings, "AI_PROVIDER_CONFIG", {})
    return config.get("backend", "custom")


def get_budget_gated_provider(tenant: Tenant) -> AIProvider:
    """Point d'entree unique pour toute fonction IA de ce depot (AI2-AI7).

    Renvoie `StubAIProvider` — sans jamais instancier ni appeler le
    connecteur reel — dans deux cas :

    1. le budget mensuel du tenant est epuise et `hard_stop=True` (garantie
       « repli-d'abord » de ce chantier) ;
    2. **le tenant n'a pas consenti a l'envoi de ses donnees vers CE
       fournisseur** (IA-9, L7). Un fournisseur configure cote deploiement
       dit ce que l'hebergeur a branche ; il ne dit pas quelle societe
       accepte que ses chiffres sortent de son serveur. Sur une instance
       multi-societes, le consentement d'une n'engage pas les autres.

    Le second garde fait de la garantie « repli-d'abord » une garantie de
    confidentialite : par defaut, aucune donnee ne sort."""
    if not check_budget(tenant):
        return StubAIProvider()
    provider = get_ai_provider()
    if isinstance(provider, StubAIProvider):
        return provider
    # Import local : `usage_budget` est importe par la passerelle, qui est
    # elle-meme importee par `apps.ai.models` en cascade — un import de
    # module creerait un cycle.
    from apps.ai.services.external_consent import has_active_consent

    if not has_active_consent(tenant, backend=_resolve_backend_label(provider)):
        logger.info(
            "Fournisseur IA externe configure mais non consenti par le tenant %s — "
            "repli sur le stub, aucune donnee ne sort (IA-9).",
            tenant.pk,
        )
        return StubAIProvider()
    return provider


def record_request(
    tenant: Tenant,
    *,
    feature: str,
    prompt_tokens_estimate: int,
    completion_tokens_estimate: int = 0,
    provider: AIProvider,
    succeeded: bool = True,
    created_by: User | None = None,
) -> AiRequest:
    return AiRequest.objects.create(
        tenant=tenant,
        feature=feature,
        prompt_tokens_estimate=prompt_tokens_estimate,
        completion_tokens_estimate=completion_tokens_estimate,
        provider_backend=_resolve_backend_label(provider),
        succeeded=succeeded,
        created_by=created_by,
    )


__all__ = [
    "DEFAULT_ALERT_THRESHOLD_PCT",
    "check_budget",
    "current_month_token_usage",
    "estimate_tokens",
    "get_budget_gated_provider",
    "get_or_create_usage_limit",
    "record_request",
]
