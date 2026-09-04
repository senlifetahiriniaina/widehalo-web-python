"""Contrat public de l'app `whatsapp` — seule surface qu'une autre app
aurait le droit d'importer (cf. tests/architecture/test_module_boundaries.py)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.whatsapp.models import WaConversation

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant


def get_conversation_status(tenant: Tenant, phone_number: str) -> dict[str, Any] | None:
    """Passe-plat de lecture — primitives uniquement, jamais l'objet
    `WaConversation`. `None` si aucune conversation n'existe encore pour ce
    numéro dans ce tenant."""
    conversation = WaConversation.objects.filter(tenant=tenant, phone_number=phone_number).first()
    if conversation is None:
        return None
    return {
        "phone_number": conversation.phone_number,
        "has_active_consent": conversation.has_active_consent(),
        "is_service_window_open": conversation.is_service_window_open(),
        "intent_state": conversation.intent_state,
        "chat_channel_id": conversation.chat_channel_id,
    }
