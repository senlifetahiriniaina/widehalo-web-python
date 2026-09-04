"""WA-1/WA-2 (cahier Phase 2 §13.4) : consentement/opt-in et sa
révocation — état COURANT porté par `WaConversation` (cf. docstring
`apps.whatsapp.models` pour la justification de ce repli plutôt qu'un
modèle `WaConsent` dédié)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.whatsapp.models import WaConversation

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User


def get_or_create_conversation(tenant: Tenant, phone_number: str) -> WaConversation:
    conversation, _created = WaConversation.objects.get_or_create(
        tenant=tenant, phone_number=phone_number
    )
    return conversation


def grant_consent(
    tenant: Tenant,
    *,
    phone_number: str,
    source: str,
    granted_by: User | None = None,
    notes: str = "",
) -> WaConversation:
    """WA-1 : « aucun envoi sans consentement enregistré. » Un octroi
    APRÈS une révocation réactive le consentement (efface `consent_
    revoked_at`) — un nouveau consentement explicite prime toujours sur
    une révocation antérieure, jamais l'inverse."""
    del notes  # reserve pour une future note libre, non persistee pour l'instant
    if not source.strip():
        raise ValidationError(_("La source du consentement est obligatoire."))
    conversation = get_or_create_conversation(tenant, phone_number)
    conversation.consent_granted_at = timezone.now()
    conversation.consent_revoked_at = None
    conversation.consent_source = source.strip()
    conversation.consent_granted_by = granted_by
    conversation.full_clean()
    conversation.save(
        update_fields=[
            "consent_granted_at",
            "consent_revoked_at",
            "consent_source",
            "consent_granted_by",
            "updated_at",
        ]
    )
    return conversation


def revoke_consent(tenant: Tenant, *, phone_number: str) -> WaConversation:
    """WA-2 : révocation — un numéro sans consentement actif préalable
    reste révocable sans effet (idempotent), jamais une erreur : un
    utilisateur qui clique deux fois sur « révoquer » ne doit jamais voir
    une exception."""
    conversation = get_or_create_conversation(tenant, phone_number)
    if conversation.has_active_consent():
        conversation.consent_revoked_at = timezone.now()
        conversation.save(update_fields=["consent_revoked_at", "updated_at"])
    return conversation


def has_active_consent(tenant: Tenant, phone_number: str) -> bool:
    conversation = WaConversation.objects.filter(tenant=tenant, phone_number=phone_number).first()
    return conversation is not None and conversation.has_active_consent()


__all__ = [
    "get_or_create_conversation",
    "grant_consent",
    "has_active_consent",
    "revoke_consent",
]
