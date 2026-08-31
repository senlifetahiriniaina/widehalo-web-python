from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.utils.translation import gettext as _

from apps.chat.models import ChatChannel, ChatChannelMembership, ChatMessage
from apps.core.events import publish_event
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.documents import store_document

MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024  # 25 Mo, cf. cahier des charges.


def is_channel_member(channel: ChatChannel, user: User) -> bool:
    return ChatChannelMembership.objects.filter(channel=channel, user=user).exists()


def post_message(
    *,
    channel: ChatChannel,
    sender: User,
    body: str = "",
    attachment_file: UploadedFile[Any] | None = None,
) -> ChatMessage:
    """Publie un message dans un canal — emet l'evenement `chat.message_created`
    (consomme par le consumer WebSocket pour la diffusion temps reel, et
    disponible pour tout futur module qui voudrait reagir a un message)."""
    attachment = None
    if attachment_file is not None:
        if (attachment_file.size or 0) > MAX_ATTACHMENT_SIZE:
            raise ValidationError(_("Pièce jointe trop volumineuse (25 Mo maximum)."))
        attachment = store_document(
            tenant=channel.tenant,
            uploaded_file=attachment_file,
            uploaded_by=sender,
            content_object=channel,
        )

    message = ChatMessage.objects.create(
        tenant=channel.tenant,
        channel=channel,
        sender=sender,
        created_by=sender,
        body=body,
        attachment=attachment,
    )

    publish_event(
        "chat.message_created",
        {
            "message_id": str(message.id),
            "channel_id": str(channel.id),
            "sender_id": str(sender.id),
            "body": body,
        },
        tenant_id=str(channel.tenant_id),
    )
    return message


def get_or_create_direct_channel(*, tenant: Tenant, participants: list[User]) -> ChatChannel:
    channel = ChatChannel.objects.create(tenant=tenant, kind=ChatChannel.KIND_DIRECT)
    for user in participants:
        ChatChannelMembership.objects.create(tenant=tenant, channel=channel, user=user)
    return channel
