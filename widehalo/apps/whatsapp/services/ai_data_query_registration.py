"""WA-9 (cahier Phase 2 §13.4) : intégration en lecture seule aux outils
IA — enregistrement des tools `whatsapp` dans le registre partagé `core.
services.data_query_tool_registry`, appelé depuis `apps.py::ready()` —
même patron exact que `apps.helpdesk.services.ai_data_query_registration`
déjà établi dans ce dépôt (`_tool_*(tenant, user, **kwargs)`)."""

from __future__ import annotations

from typing import Any

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.data_query_tool_registry import register_data_query_tool


def _tool_conversation_status(
    tenant: Tenant, user: User, *, phone_number: str
) -> list[dict[str, Any]]:
    del user  # RBAC deja applique en amont par le filtrage `required_permission`
    from apps.whatsapp.services.public import get_conversation_status

    status = get_conversation_status(tenant, phone_number)
    return [status] if status is not None else []


def register_ai_data_query_tools() -> None:
    register_data_query_tool(
        "whatsapp.conversation_status",
        module="whatsapp",
        label="État d'une conversation WhatsApp",
        description=(
            "Consentement actif, fenêtre de service ouverte, état du menu "
            "d'intentions et canal de discussion interne pour un numéro de "
            "téléphone donné. Utile pour répondre à 'peut-on encore contacter "
            "ce client par WhatsApp ?' ou 'où en est cette conversation ?'."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "phone_number": {
                    "type": "string",
                    "description": "Numéro de téléphone au format international",
                },
            },
            "required": ["phone_number"],
        },
        required_permission="whatsapp.view_waconversation",
        function=_tool_conversation_status,
    )


__all__ = ["register_ai_data_query_tools"]
