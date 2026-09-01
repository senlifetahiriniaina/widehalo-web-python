from __future__ import annotations

from typing import cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.chat.models import ChatChannel, ChatMessage
from apps.chat.services.messaging import (
    get_or_create_direct_channel,
    is_channel_member,
    post_message,
)
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership


def _resolve_tenant_id(request: HttpRequest) -> str:
    """Meme idiome de resolution de tenant courant que le reste du depot
    (ex. `apps.core.views.pages.instant_search_fragment`) : en-tete
    `X-Tenant-Id` (appels HTMX/API) sinon session (navigation classique)."""
    return request.headers.get("X-Tenant-Id") or request.session.get("tenant_id") or ""


@login_required
def chat_home(request: HttpRequest, channel_id: str | None = None) -> HttpResponse:
    """Ecran minimal : liste des canaux de l'utilisateur + fil du canal
    ouvert. Repli HTMX polling 10s (`hx-trigger="every 10s"`) sur le fragment
    de messages — si le WebSocket du navigateur echoue, ce polling continue
    de faire vivre la conversation sans jamais recharger la page complete.

    Le meme ecran porte aussi un formulaire HTML simple d'envoi de message
    (repli non-JS/non-WebSocket, symetrique du polling cote reception) : un
    POST avec un champ `body` sur cette meme URL poste directement via
    `post_message()`, puis redirige vers le canal (dont le fragment se
    recharge par le polling deja en place, sans JS requis pour fonctionner)."""
    user = cast(User, request.user)
    error = None

    if request.method == "POST" and channel_id is not None and "body" in request.POST:
        channel = get_object_or_404(ChatChannel, id=channel_id)
        if not is_channel_member(channel, user):
            return HttpResponse(status=403)
        try:
            post_message(
                channel=channel,
                sender=user,
                body=request.POST.get("body", ""),
                attachment_file=request.FILES.get("attachment"),
            )
        except ValidationError as exc:
            error = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        else:
            return redirect("chat:channel", channel_id=channel_id)

    channels = ChatChannel.objects.filter(memberships__user=user).distinct()
    return render(
        request,
        "chat/home.html",
        {"channels": channels, "active_channel_id": channel_id, "error": error},
    )


@login_required
def chat_new_conversation(request: HttpRequest) -> HttpResponse:
    """Action « Nouvelle conversation » : choix d'un autre utilisateur puis
    `get_or_create_direct_channel()`, redirection vers le canal cree.

    **Correctif de bug reel (UXR2)** : la liste des correspondants
    proposes est desormais scopee au tenant courant (via
    `UserTenantMembership`), au lieu de `User.objects.exclude(...)` qui
    proposait tout utilisateur de la base entiere, tous tenants confondus."""
    user = cast(User, request.user)
    tenant_id = _resolve_tenant_id(request)

    if request.method == "POST":
        other_user = get_object_or_404(User, id=request.POST.get("other_user_id"))
        tenant = get_object_or_404(Tenant, id=tenant_id)
        channel = get_or_create_direct_channel(tenant=tenant, participants=[user, other_user])
        return redirect("chat:channel", channel_id=channel.id)

    other_users = (
        User.objects.filter(
            tenant_memberships__tenant_id=tenant_id,
        )
        .exclude(id=user.id)
        .distinct()
    )
    return render(request, "chat/new_conversation.html", {"other_users": other_users})


@login_required
def chat_launcher(request: HttpRequest) -> HttpResponse:
    """Contenu de la popup lancee par le bouton flottant (`whModal()`,
    `base.html`) : liste des canaux existants de l'utilisateur (meme
    requete condensee que `chat_home`) + formulaire « Nouvelle
    conversation » (recherche instantanee tenant-scopee + premier
    message), sans jamais reimplementer la messagerie temps reelle a
    l'interieur de la popup — celle-ci reste sur `/chat/<id>/`."""
    user = cast(User, request.user)
    channels = ChatChannel.objects.filter(memberships__user=user).distinct()
    return render(request, "chat/_launcher.html", {"channels": channels})


@login_required
def chat_launcher_users(request: HttpRequest) -> HttpResponse:
    """Recherche instantanee (HTMX, meme patron que `instant_search_fragment`)
    d'un correspondant pour « Nouvelle conversation » depuis la popup —
    tenant-scopee via `UserTenantMembership` (jamais tous les utilisateurs
    de la base, meme correctif que `chat_new_conversation` ci-dessus)."""
    user = cast(User, request.user)
    tenant_id = _resolve_tenant_id(request)
    query = request.GET.get("q", "").strip()

    memberships = (
        UserTenantMembership.objects.filter(tenant_id=tenant_id)
        .exclude(user=user)
        .select_related("user")
    )
    if query:
        memberships = memberships.filter(user__email__icontains=query)

    other_users = [membership.user for membership in memberships[:20]]
    return render(request, "chat/_launcher_users.html", {"other_users": other_users})


@login_required
def chat_launcher_start(request: HttpRequest) -> HttpResponse:
    """Action de soumission de la popup : cree/retrouve le canal direct
    (`get_or_create_direct_channel`, desormais idempotent, cf. correctif
    UXR2) ET poste le premier message dans le meme appel HTMX, puis
    demande au navigateur de naviguer vers l'ecran complet `/chat/<id>/`
    via l'en-tete `HX-Redirect` (deja natif htmx, ferme la popup de facto
    puisque la page change)."""
    user = cast(User, request.user)
    if request.method != "POST":
        return HttpResponse(status=405)

    tenant_id = _resolve_tenant_id(request)
    tenant = get_object_or_404(Tenant, id=tenant_id)
    other_user = get_object_or_404(
        User.objects.filter(tenant_memberships__tenant=tenant),
        id=request.POST.get("other_user_id"),
    )

    channel = get_or_create_direct_channel(tenant=tenant, participants=[user, other_user])

    body = request.POST.get("body", "").strip()
    if body:
        post_message(channel=channel, sender=user, body=body)

    response = HttpResponse(status=204)
    response["HX-Redirect"] = f"/chat/{channel.id}/"
    return response


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
