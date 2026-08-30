"""Suggestion de reponse assistee par IA sur un ticket (HD3, cf. plan
« Suggestion de reponse a l'agent » — remplace la « suggestion de reponse
IA A/B testee » ecartee du document source, decision de perimetre n°2).

**Discipline « fallback-first » mandatee pour TOUTE fonction IA de ce
depot** (identique a `apps.ai.services.contextual_assistant.assist`,
`apps.projects.services.ai_assistant`...) : le SEUL point d'entree
autorise pour obtenir un fournisseur IA est `get_budget_gated_provider`
(re-expose par `apps.ai.services.public`, cf. sa docstring — jamais
`apps.core.services.ai_assistant.get_ai_provider()` appele directement,
qui contournerait la garde de budget). `suggest_reply()` :
- ne fait JAMAIS d'appel reseau si le fournisseur resolu est
  `StubAIProvider` (non configure OU budget mensuel epuise) — renvoie une
  chaine vide immediatement, sans jamais toucher `provider.complete()` ;
- degrade silencieusement vers la chaine vide si `provider.complete()`
  leve `AIProviderError` (echec reseau/HTTP d'un connecteur reel) ;
- ne leve JAMAIS d'exception vers l'appelant, quel que soit l'etat du
  systeme — meme garantie que `assist()`/`suggest_next_actions` ailleurs
  dans ce depot.

**Journalisation** : seul un VRAI appel LLM (succes ou `AIProviderError`)
est journalise via `record_request` — meme decision disclosed que
`contextual_assistant.assist` (le chemin stub n'ecrit jamais de
`AiRequest`, cout nul, aucun signal de suivi a en tirer).

**`feature` journalise** : `"helpdesk_reply"` — valeur AJOUTEE de facon
ADDITIVE a `apps.ai.models.AiRequest.FEATURE_CHOICES` (jamais un retrait/
renommage d'une valeur existante), cf. ce fichier pour le detail. Reprise
ICI comme simple constante Python litterale plutot qu'un import de
`apps.ai.models.AiRequest` (regle de couplage n°1 : `helpdesk` ne peut
importer que `apps.ai.services.public`, jamais un modele de `ai`) — meme
discipline exacte que `apps.helpdesk.models.SECTOR_CHOICES` (constantes
dupliquees par convention documentee plutot qu'un import interdit).
`record_request(feature=...)` accepte de toute facon un `str` libre (pas
un `Enum`), donc cette duplication n'a aucun risque de decalage de type."""

from __future__ import annotations

from apps.ai.services.public import estimate_tokens, get_budget_gated_provider, record_request
from apps.core.models.tenant import Tenant
from apps.core.services.ai_assistant import AIProviderError, StubAIProvider
from apps.helpdesk.models import HlpTicket

FEATURE_HELPDESK_REPLY = "helpdesk_reply"

_MAX_RECENT_COMMENTS = 5
_SUGGESTION_MAX_TOKENS = 400


def _build_prompt(ticket: HlpTicket) -> str:
    parts = [
        "Tu es un agent support interne. Redige une proposition de reponse "
        "concise et professionnelle au ticket suivant.",
        f"Sujet : {ticket.subject}",
        f"Description : {ticket.description}" if ticket.description else "",
    ]
    # Commentaires NON internes uniquement (jamais une note interne entre
    # agents dans un prompt destine a produire une reponse VISIBLE par le
    # demandeur) — les `_MAX_RECENT_COMMENTS` plus recents suffisent pour
    # donner le contexte de l'echange sans faire exploser la taille du
    # prompt sur un fil de suivi long.
    recent_comments = list(
        ticket.comments.filter(is_internal_note=False).order_by("-created_at")[
            :_MAX_RECENT_COMMENTS
        ]
    )
    for comment in reversed(recent_comments):
        author_label = str(comment.author) if comment.author_id else "—"
        parts.append(f"[{author_label}] {comment.body}")
    return "\n".join(part for part in parts if part)


def suggest_reply(ticket: HlpTicket, *, tenant: Tenant) -> str:
    """Retourne un texte de reponse suggere, ou une chaine vide si aucune
    suggestion n'est disponible (fournisseur non configure, budget epuise,
    ou echec du connecteur reel) — JAMAIS une exception, cf. docstring de
    tete de module."""
    provider = get_budget_gated_provider(tenant)
    if isinstance(provider, StubAIProvider):
        return ""

    prompt = _build_prompt(ticket)
    try:
        completion = provider.complete(prompt, max_tokens=_SUGGESTION_MAX_TOKENS)
    except AIProviderError:
        record_request(
            tenant,
            feature=FEATURE_HELPDESK_REPLY,
            prompt_tokens_estimate=estimate_tokens(prompt),
            completion_tokens_estimate=0,
            provider=provider,
            succeeded=False,
        )
        return ""

    record_request(
        tenant,
        feature=FEATURE_HELPDESK_REPLY,
        prompt_tokens_estimate=estimate_tokens(prompt),
        completion_tokens_estimate=estimate_tokens(completion),
        provider=provider,
        succeeded=True,
    )
    return completion


__all__ = ["suggest_reply"]
