"""Contrat public de l'app `chat` — seule surface que les autres apps
metier ont le droit d'importer (cf. tests/architecture/test_module_boundaries.py).
Ne jamais importer `apps.chat.models` depuis un autre module."""

from __future__ import annotations

from typing import Any

from django.contrib.contenttypes.models import ContentType

from apps.chat.models import ChatChannel, ChatChannelMembership
from apps.core.models.tenant import Tenant
from apps.core.models.user import User


def get_or_create_document_channel(
    *, tenant: Tenant, content_object: Any, participants: list[User], title: str = ""
) -> str:
    """Ouvre (ou retrouve) le canal de discussion rattache a un objet
    metier quelconque (facture, commande, ticket...) via content-type
    generique. Retourne l'id du canal (str) — jamais l'objet ORM, pour ne
    pas exposer le modele `ChatChannel` hors de cette app."""
    content_type = ContentType.objects.get_for_model(content_object.__class__)
    object_id = str(content_object.pk)

    channel = ChatChannel.objects.filter(
        tenant=tenant, content_type=content_type, object_id=object_id
    ).first()
    if channel is None:
        channel = ChatChannel.objects.create(
            tenant=tenant,
            kind=ChatChannel.KIND_CONTEXT,
            content_type=content_type,
            object_id=object_id,
            title=title,
        )

    existing_member_ids = set(
        ChatChannelMembership.objects.filter(channel=channel).values_list("user_id", flat=True)
    )
    for user in participants:
        if user.id not in existing_member_ids:
            ChatChannelMembership.objects.create(tenant=tenant, channel=channel, user=user)

    return str(channel.id)
