from __future__ import annotations

from typing import cast

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.chat.models import ChatChannel, ChatMessage
from apps.chat.services.messaging import is_channel_member
from apps.core.models.user import User


@login_required
def chat_home(request: HttpRequest, channel_id: str | None = None) -> HttpResponse:
    """Ecran minimal : liste des canaux de l'utilisateur + fil du canal
    ouvert. Repli HTMX polling 10s (`hx-trigger="every 10s"`) sur le fragment
    de messages — si le WebSocket du navigateur echoue, ce polling continue
    de faire vivre la conversation sans jamais recharger la page complete."""
    user = cast(User, request.user)
    channels = ChatChannel.objects.filter(memberships__user=user).distinct()
    return render(
        request, "chat/home.html", {"channels": channels, "active_channel_id": channel_id}
    )


@login_required
def chat_messages_fragment(request: HttpRequest, channel_id: str) -> HttpResponse:
    user = cast(User, request.user)
    channel = get_object_or_404(ChatChannel, id=channel_id)
    if not is_channel_member(channel, user):
        return HttpResponse(status=403)

    since = request.GET.get("since", "")
    messages = channel.messages.all()
    if since:
        since_message = ChatMessage.objects.filter(id=since).first()
        if since_message is not None:
            messages = messages.filter(created_at__gt=since_message.created_at)

    return render(
        request,
        "chat/_messages_fragment.html",
        {"channel": channel, "messages": messages},
    )
