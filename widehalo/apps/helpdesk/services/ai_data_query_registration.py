"""Passerelle IA locale d'analyse de donnees (GW3) : enregistrement des
tools `helpdesk` dans le registre partage `core.services.data_query_tool_
registry`, appele depuis `apps.py::ready()` — meme patron exact que
`apps.sales.services.ai_data_query_registration` deja etabli dans ce
chantier (`_tool_*(tenant, user, **kwargs)`, `apps.ai.services.
data_query_gateway._run_tool_calling_loop` appelant `tool.function(tenant,
user, **call.arguments)` — signature confirmee par lecture directe de ce
fichier avant d'ecrire ce module).

**`helpdesk.ticket_summary`** : enveloppe une petite agregation DEJA
triviale sur `HlpTicket` (comptes ouverts/resolus/clotures/escalades,
filtrage optionnel par equipe/priorite) — aucune fonction `services/
reports.py` existante ne renvoie exactement cette forme (les fonctions de
HD4 sont deja des rapports periode/regroupement plus riches), donc la
petite agregation vit directement ici plutot que d'etre artificiellement
poussee dans `services/reports.py` pour ce seul besoin. `required_
permission="helpdesk.view_hlpticket"` — meme permission auto-generee
Django que celle qui gate deja la lecture des tickets (RBAC app-level HD1,
`ROLE_APP_PERMISSIONS["helpdesk"]` accorde `view` a tous les roles).

**`helpdesk.search_kb`** : enveloppe directement `apps.helpdesk.services.
kb.search_articles` (HD3, deja teste), sans reimplementation.
`required_permission="helpdesk.view_hlpkbarticle"` — meme permission
auto-generee Django que celle deja accordee par la posture RBAC
DELIBEREMENT OUVERTE de HD3 (KB partagee, tous les roles, cf. docstring
`services/kb.py`/plan section HD3 TERMINÉ)."""

from __future__ import annotations

from typing import Any

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.data_query_tool_registry import register_data_query_tool


def _tool_ticket_summary(
    tenant: Tenant, user: User, *, team_id: str = "", priority: str = ""
) -> list[dict[str, Any]]:
    del user  # RBAC deja applique en amont par le filtrage `required_permission`
    from apps.helpdesk.models import HlpTicket

    queryset = HlpTicket.objects.filter(tenant=tenant, is_active=True)
    if team_id:
        queryset = queryset.filter(team__id=team_id)
    if priority:
        queryset = queryset.filter(priority=priority)

    return [
        {
            "open_count": queryset.filter(state__in=HlpTicket.ACTIVE_STATES).count(),
            "resolved_count": queryset.filter(state=HlpTicket.STATE_RESOLVED).count(),
            "closed_count": queryset.filter(state=HlpTicket.STATE_CLOSED).count(),
            "escalated_count": queryset.filter(state=HlpTicket.STATE_ESCALATED).count(),
        }
    ]


def _tool_search_kb(tenant: Tenant, user: User, *, query: str = "") -> list[dict[str, Any]]:
    del user  # RBAC deja applique en amont par le filtrage `required_permission`
    from apps.helpdesk.services.kb import search_articles

    articles = search_articles(tenant, query)[:10]
    return [
        {"id": str(article.id), "title": article.title, "excerpt": article.body[:280]}
        for article in articles
    ]


def register_ai_data_query_tools() -> None:
    register_data_query_tool(
        "helpdesk.ticket_summary",
        module="helpdesk",
        label="Synthese des tickets (ouverts/resolus/clotures/escalades)",
        description=(
            "Compte de tickets helpdesk par statut (ouverts, resolus, clotures, "
            "escalades), avec filtrage optionnel par equipe ou priorite. Utile "
            "pour repondre a des questions du type 'combien de tickets escalades "
            "en ce moment ?'."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "team_id": {
                    "type": "string",
                    "description": "Identifiant de l'equipe pour filtrer (optionnel)",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "normal", "high", "urgent"],
                    "description": "Priorite pour filtrer (optionnel)",
                },
            },
            "required": [],
        },
        required_permission="helpdesk.view_hlpticket",
        read_only=True,
        function=_tool_ticket_summary,
    )
    register_data_query_tool(
        "helpdesk.search_kb",
        module="helpdesk",
        label="Recherche dans la base de connaissances interne",
        description=(
            "Recherche simple (titre/contenu) dans les articles publies de la "
            "base de connaissances interne helpdesk. Utile pour repondre a une "
            "question en s'appuyant sur un article existant plutot que d'inventer "
            "une reponse."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Termes de recherche"},
            },
            "required": ["query"],
        },
        required_permission="helpdesk.view_hlpkbarticle",
        read_only=True,
        function=_tool_search_kb,
    )


__all__ = ["register_ai_data_query_tools"]
