"""AI2 : auto-enregistrement de la guidance statique du module `helpdesk`
dans `core.services.ai_context_registry`, appele depuis `apps.py::ready()`
— meme patron exact que `apps.sales.services.ai_context_registration`/
`apps.mrp.services.ai_context_registration` deja etablis dans ce chantier.

**18e module a s'enregistrer** (17 deja faits en AI2, cf. plan section HD5)
— `helpdesk` rejoint simplement la liste existante, aucune manipulation
speciale requise.

**`context_builder`** : contrairement a `sales`/`mrp` (guidance statique
seule), `helpdesk` enrichit le prompt avec deux compteurs REELS du tenant
(ticket ouverts au sens SLA/escalade, ticket actuellement escalades) —
memes deux notions exactes que `HlpTicket.ACTIVE_STATES`/`STATE_ESCALATED`
deja utilisees par `services.escalation`/`services.reports`, jamais un
nouveau calcul invente pour ce seul besoin de contexte IA."""

from __future__ import annotations

from typing import Any

from apps.core.services.ai_context_registry import register_context

_GUIDANCE_FR = (
    "Support et suivi operationnel (helpdesk) : tickets de demandes et "
    "d'incidents rattaches aux operations (rattachement generique a "
    "n'importe quel enregistrement d'un autre module), SLA et escalade "
    "deterministes, base de connaissances interne, gabarits de reponse et "
    "enquetes de satisfaction post-resolution."
)
_GUIDANCE_EN = (
    "Support and operational tracking (helpdesk): request and incident "
    "tickets linked to operations (generic reference to any record from "
    "another module), deterministic SLA and escalation, internal knowledge "
    "base, response templates and post-resolution satisfaction surveys."
)


def _build_context(tenant_id: str) -> dict[str, Any]:
    """Compteurs REELS du tenant, jamais inventes — un ticket "ouvert" au
    sens `HlpTicket.ACTIVE_STATES` (new/in_progress/pending/escalated,
    exclut resolved/closed/cancelled), et le sous-ensemble deja escalade."""
    from apps.helpdesk.models import HlpTicket

    open_count = HlpTicket.objects.filter(
        tenant_id=tenant_id, state__in=HlpTicket.ACTIVE_STATES
    ).count()
    escalated_count = HlpTicket.objects.filter(
        tenant_id=tenant_id, state=HlpTicket.STATE_ESCALATED
    ).count()
    return {
        "open_ticket_count": open_count,
        "escalated_ticket_count": escalated_count,
    }


def register_ai_context() -> None:
    register_context(
        "helpdesk",
        static_guidance_fr=_GUIDANCE_FR,
        static_guidance_en=_GUIDANCE_EN,
        context_builder=_build_context,
    )
