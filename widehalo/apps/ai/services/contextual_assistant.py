"""AI2 — Assistant contextuel par page/action (cf. plan section « Module
`ai` (Intelligence artificielle transversale) »). Point d'entree unique :
`assist(module, action, tenant=..., user=..., locale=...)`.

**Discipline « fallback-first » (identique a tout le chantier `ai`)** :
`assist()` ne leve JAMAIS d'exception cote appelant, quel que soit l'etat du
registre (`apps.core.services.ai_context_registry`), du budget de tokens
(`apps.ai.services.usage_budget`) ou du connecteur IA reel
(`apps.core.services.ai_assistant`) :
- module non enregistre -> message de repli generique bilingue ;
- module enregistre mais provider = `StubAIProvider` (non configure OU
  budget epuise, cf. `get_budget_gated_provider`) -> guidance statique du
  module, `is_ai_generated=False` ;
- module enregistre + provider reel disponible -> prompt = guidance statique
  + contexte reel optionnel (`context_builder`) + `action`, complete par
  `provider.complete()` ; toute `AIProviderError` retombe silencieusement
  sur la guidance statique.

**Portee MVP disclosed** : un seul champ `guidance` (texte libre) plutot que
la structure riche evoquee par l'ancienne specification Laravel (etapes
numerotees, indicateurs de decision, avertissements de conformite...) —
batir un schema structure sans donnees d'usage reelles pour en valider la
forme serait speculatif a ce stade ; `suggested_next_actions` reste present
dans le type de retour (toujours vide pour l'instant) pour ne pas fermer la
porte a un futur enrichissement sans casser le contrat.

**Cache** (Redis via `django.core.cache.cache`, meme idiome que
`apps.core.throttling`) : cle `ai_assist:{module}:{action}:{locale}:
{role_code}:{context_hash}`, TTL 300s. Un hit renvoie la reponse en cache
SANS jamais retoucher le registre, le budget ni le provider — donc sans
generer de second appel LLM ni de second enregistrement `AiRequest`.

**Journalisation (`AiRequest`, decision disclosed)** : seule une reponse
issue d'un VRAI appel LLM (succes ou `AIProviderError`) est journalisee via
`record_request`. Le cas "guidance statique" (module non enregistre, ou
enregistre mais provider = stub) n'entraine AUCUNE ecriture `AiRequest` —
cout nul, aucune valeur de suivi de budget/observabilite a en tirer, et ce
chemin peut etre emprunte tres frequemment (chaque changement de page) :
journaliser systematiquement aurait ajoute une ecriture DB par navigation
sans aucun signal utile derriere. Documente ici plutot que suppose."""

from __future__ import annotations

import hashlib
import json
from typing import TypedDict, cast

from django.core.cache import cache

from apps.ai.models import AiRequest
from apps.ai.services.usage_budget import estimate_tokens, get_budget_gated_provider, record_request
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.ai_assistant import AIProviderError, StubAIProvider
from apps.core.services.ai_context_registry import RegisteredContext, get_context
from apps.core.services.permissions import user_role_codes

_CACHE_TTL_SECONDS = 300

_FALLBACK_GUIDANCE_FR = (
    "Aucune guidance n'est encore enregistree pour ce module — revenez "
    "plus tard ou consultez la documentation du module."
)
_FALLBACK_GUIDANCE_EN = (
    "No guidance is registered for this module yet — check back later or "
    "consult the module's documentation."
)


class AssistResponse(TypedDict):
    module: str
    action: str
    guidance: str
    is_ai_generated: bool
    suggested_next_actions: list[str]


def _is_english(locale: str) -> bool:
    return locale.lower().startswith("en")


def _static_guidance(registered: RegisteredContext, locale: str) -> str:
    return registered.static_guidance_en if _is_english(locale) else registered.static_guidance_fr


def _role_code(user: User) -> str:
    codes = sorted(user_role_codes(user))
    return "-".join(codes) if codes else "anon"


def _context_hash(context_data: dict[str, object] | None) -> str:
    if context_data is None:
        return "none"
    payload = json.dumps(context_data, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _build_prompt(static_guidance: str, action: str, context_data: dict[str, object]) -> str:
    parts = [static_guidance, f"Action demandee : {action}"]
    if context_data:
        parts.append(f"Contexte tenant (JSON) : {json.dumps(context_data, default=str)}")
    return "\n\n".join(parts)


def assist(module: str, action: str, *, tenant: Tenant, user: User, locale: str) -> AssistResponse:
    registered = get_context(module)
    if registered is None:
        guidance = _FALLBACK_GUIDANCE_EN if _is_english(locale) else _FALLBACK_GUIDANCE_FR
        return AssistResponse(
            module=module,
            action=action,
            guidance=guidance,
            is_ai_generated=False,
            suggested_next_actions=[],
        )

    context_data: dict[str, object] = {}
    if registered.context_builder is not None:
        context_data = registered.context_builder(str(tenant.id))

    cache_key = (
        f"ai_assist:{module}:{action}:{locale}:{_role_code(user)}:{_context_hash(context_data)}"
    )
    cached = cache.get(cache_key)
    if cached is not None:
        # `cache.get()` renvoie `Any` (dict serialise par `cache.set()`
        # ci-dessous, forme garantie par construction) — cast plutot qu'un
        # `AssistResponse(**cached)` que mypy ne peut pas verifier
        # statiquement (les cles proviennent d'un dict opaque cote types).
        return cast(AssistResponse, cached)

    static_guidance = _static_guidance(registered, locale)
    provider = get_budget_gated_provider(tenant)

    if isinstance(provider, StubAIProvider):
        response: AssistResponse = AssistResponse(
            module=module,
            action=action,
            guidance=static_guidance,
            is_ai_generated=False,
            suggested_next_actions=[],
        )
        cache.set(cache_key, dict(response), timeout=_CACHE_TTL_SECONDS)
        return response

    prompt = _build_prompt(static_guidance, action, context_data)
    try:
        completion = provider.complete(prompt)
    except AIProviderError:
        record_request(
            tenant,
            feature=AiRequest.FEATURE_ASSIST,
            prompt_tokens_estimate=estimate_tokens(prompt),
            completion_tokens_estimate=0,
            provider=provider,
            succeeded=False,
            created_by=user,
        )
        response = AssistResponse(
            module=module,
            action=action,
            guidance=static_guidance,
            is_ai_generated=False,
            suggested_next_actions=[],
        )
        cache.set(cache_key, dict(response), timeout=_CACHE_TTL_SECONDS)
        return response

    record_request(
        tenant,
        feature=AiRequest.FEATURE_ASSIST,
        prompt_tokens_estimate=estimate_tokens(prompt),
        completion_tokens_estimate=estimate_tokens(completion),
        provider=provider,
        succeeded=True,
        created_by=user,
    )
    response = AssistResponse(
        module=module,
        action=action,
        guidance=completion,
        is_ai_generated=True,
        suggested_next_actions=[],
    )
    cache.set(cache_key, dict(response), timeout=_CACHE_TTL_SECONDS)
    return response


__all__ = ["AssistResponse", "assist"]
