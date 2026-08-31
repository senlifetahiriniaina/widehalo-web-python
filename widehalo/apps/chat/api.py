"""API HTTP de l'app chat : sert a la fois l'ecran (creation de canal,
historique) et le REPLI HTMX polling 10s obligatoire si le WebSocket
echoue (`GET /chat/channels/{id}/messages?since=...`, cf. Fait-quand de
l'etape 12)."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from ninja import File, Form, Router
from ninja.files import UploadedFile

from apps.chat.models import ChatChannel, ChatMessage
from apps.chat.services.messaging import is_channel_member, post_message

router = Router(tags=["chat"])


def _serialize_message(message: ChatMessage) -> dict:
    return {
        "id": str(message.id),
        "channel_id": str(message.channel_id),
        "sender_id": str(message.sender_id) if message.sender_id else None,
        "body": message.body,
        "attachment_id": str(message.attachment_id) if message.attachment_id else None,
        "created_at": message.created_at.isoformat(),
    }


@router.get("/chat/channels")
def list_channels(request):
    channels = ChatChannel.objects.filter(memberships__user=request.auth)
    return {
        "results": [
            {"id": str(c.id), "kind": c.kind, "title": c.title} for c in channels.distinct()
        ]
    }


@router.get("/chat/channels/{channel_id}/messages")
def list_messages(request, channel_id: str, since: str = ""):
    """Utilise a la fois pour l'historique initial et pour le polling HTMX
    de repli (rejoue toutes les 10s avec `since` = id du dernier message
    deja affiche)."""
    channel = get_object_or_404(ChatChannel, id=channel_id)
    if not is_channel_member(channel, request.auth):
        return JsonResponse({"detail": _("Vous n'êtes pas membre de ce canal.")}, status=403)

    messages = channel.messages.all()
    if since:
        since_message = ChatMessage.objects.filter(id=since).first()
        if since_message is not None:
            messages = messages.filter(created_at__gt=since_message.created_at)

    return {"results": [_serialize_message(m) for m in messages]}


@router.post("/chat/channels/{channel_id}/messages")
def create_message(
    request,
    channel_id: str,
    body: str = Form(""),
    attachment: UploadedFile = File(None),  # noqa: B008 — idiome django-ninja standard
):
    channel = get_object_or_404(ChatChannel, id=channel_id)
    if not is_channel_member(channel, request.auth):
        return JsonResponse({"detail": _("Vous n'êtes pas membre de ce canal.")}, status=403)

    try:
        message = post_message(
            channel=channel, sender=request.auth, body=body, attachment_file=attachment
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)

    return _serialize_message(message)
