from __future__ import annotations

import pytest
from apps.chat.models import ChatChannel, ChatChannelMembership, ChatMessage
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.tests.utils import use_tenant
from bs4 import BeautifulSoup
from django.test import Client

pytestmark = pytest.mark.django_db


def _login_with_tenant(tenant: Tenant, user: User) -> Client:
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def test_send_message_via_html_form_fallback() -> None:
    tenant = Tenant.objects.create(code="UI-CHAT", name="UI Chat Tenant")
    user = User.objects.create_user(email="ui-chat@example.com", password="Str0ngPassw0rd!23")
    client = _login_with_tenant(tenant, user)

    with use_tenant(tenant.id):
        channel = ChatChannel.objects.create(tenant=tenant, kind=ChatChannel.KIND_DIRECT)
        ChatChannelMembership.objects.create(tenant=tenant, channel=channel, user=user)

    form_response = client.get(f"/chat/{channel.id}/")
    assert form_response.status_code == 200
    assert "Envoyer" in form_response.content.decode()

    response = client.post(f"/chat/{channel.id}/", {"body": "Bonjour via le formulaire HTML"})
    assert response.status_code == 302
    assert response.url == f"/chat/{channel.id}/"

    with use_tenant(tenant.id):
        assert ChatMessage.objects.filter(
            channel=channel, body="Bonjour via le formulaire HTML"
        ).exists()


def test_send_message_rejected_for_non_member() -> None:
    tenant = Tenant.objects.create(code="UI-CHAT2", name="UI Chat Tenant 2")
    member = User.objects.create_user(email="ui-chat2a@example.com", password="Str0ngPassw0rd!23")
    outsider = User.objects.create_user(email="ui-chat2b@example.com", password="Str0ngPassw0rd!23")

    with use_tenant(tenant.id):
        channel = ChatChannel.objects.create(tenant=tenant, kind=ChatChannel.KIND_DIRECT)
        ChatChannelMembership.objects.create(tenant=tenant, channel=channel, user=member)

    client = _login_with_tenant(tenant, outsider)
    response = client.post(f"/chat/{channel.id}/", {"body": "Intrusion"})
    assert response.status_code == 403


def test_new_conversation_creates_direct_channel() -> None:
    tenant = Tenant.objects.create(code="UI-CHAT3", name="UI Chat Tenant 3")
    user = User.objects.create_user(email="ui-chat3a@example.com", password="Str0ngPassw0rd!23")
    other = User.objects.create_user(email="ui-chat3b@example.com", password="Str0ngPassw0rd!23")
    UserTenantMembership.objects.create(user=user, tenant=tenant)
    UserTenantMembership.objects.create(user=other, tenant=tenant)
    client = _login_with_tenant(tenant, user)

    form_response = client.get("/chat/new/")
    assert form_response.status_code == 200
    assert other.email in form_response.content.decode()

    response = client.post("/chat/new/", {"other_user_id": str(other.id)})
    assert response.status_code == 302

    with use_tenant(tenant.id):
        channel = ChatChannel.objects.get(kind=ChatChannel.KIND_DIRECT)
        assert response.url == f"/chat/{channel.id}/"
        member_ids = set(
            ChatChannelMembership.objects.filter(channel=channel).values_list("user_id", flat=True)
        )
        assert member_ids == {user.id, other.id}


def test_new_conversation_list_is_scoped_to_the_current_tenant() -> None:
    """Correctif de bug reel (UXR2) : `chat_new_conversation` ne doit plus
    proposer un utilisateur d'un AUTRE tenant (`User.objects.exclude(...)`
    parcourait auparavant toute la base, tous tenants confondus)."""
    tenant = Tenant.objects.create(code="UI-CHAT4", name="UI Chat Tenant 4")
    other_tenant = Tenant.objects.create(code="UI-CHAT4-OTHER", name="UI Chat Tenant 4 Other")
    user = User.objects.create_user(email="ui-chat4a@example.com", password="Str0ngPassw0rd!23")
    same_tenant_user = User.objects.create_user(
        email="ui-chat4b@example.com", password="Str0ngPassw0rd!23"
    )
    other_tenant_user = User.objects.create_user(
        email="ui-chat4c@example.com", password="Str0ngPassw0rd!23"
    )
    UserTenantMembership.objects.create(user=user, tenant=tenant)
    UserTenantMembership.objects.create(user=same_tenant_user, tenant=tenant)
    UserTenantMembership.objects.create(user=other_tenant_user, tenant=other_tenant)

    client = _login_with_tenant(tenant, user)
    content = client.get("/chat/new/").content.decode()

    assert same_tenant_user.email in content
    assert other_tenant_user.email not in content


def test_launcher_users_search_is_scoped_to_the_current_tenant() -> None:
    tenant = Tenant.objects.create(code="UI-CHAT5", name="UI Chat Tenant 5")
    other_tenant = Tenant.objects.create(code="UI-CHAT5-OTHER", name="UI Chat Tenant 5 Other")
    user = User.objects.create_user(email="ui-chat5a@example.com", password="Str0ngPassw0rd!23")
    same_tenant_user = User.objects.create_user(
        email="ui-chat5b@example.com", password="Str0ngPassw0rd!23"
    )
    other_tenant_user = User.objects.create_user(
        email="ui-chat5c@example.com", password="Str0ngPassw0rd!23"
    )
    UserTenantMembership.objects.create(user=user, tenant=tenant)
    UserTenantMembership.objects.create(user=same_tenant_user, tenant=tenant)
    UserTenantMembership.objects.create(user=other_tenant_user, tenant=other_tenant)

    client = _login_with_tenant(tenant, user)
    content = client.get("/chat/launcher/users/").content.decode()

    assert same_tenant_user.email in content
    assert other_tenant_user.email not in content


def test_launcher_start_creates_channel_and_posts_first_message() -> None:
    tenant = Tenant.objects.create(code="UI-CHAT6", name="UI Chat Tenant 6")
    user = User.objects.create_user(email="ui-chat6a@example.com", password="Str0ngPassw0rd!23")
    other = User.objects.create_user(email="ui-chat6b@example.com", password="Str0ngPassw0rd!23")
    UserTenantMembership.objects.create(user=user, tenant=tenant)
    UserTenantMembership.objects.create(user=other, tenant=tenant)
    client = _login_with_tenant(tenant, user)

    response = client.post(
        "/chat/launcher/start/",
        {"other_user_id": str(other.id), "body": "Bonjour, on peut se parler ?"},
    )
    assert response.status_code == 204

    with use_tenant(tenant.id):
        channel = ChatChannel.objects.get(kind=ChatChannel.KIND_DIRECT)
        assert response["HX-Redirect"] == f"/chat/{channel.id}/"
        member_ids = set(
            ChatChannelMembership.objects.filter(channel=channel).values_list("user_id", flat=True)
        )
        assert member_ids == {user.id, other.id}
        assert ChatMessage.objects.filter(
            channel=channel, body="Bonjour, on peut se parler ?"
        ).exists()

    # Un second appel avec le meme correspondant retrouve le MEME canal
    # (correctif UXR2 de `get_or_create_direct_channel`), au lieu d'en
    # creer un second.
    second_response = client.post(
        "/chat/launcher/start/",
        {"other_user_id": str(other.id), "body": "Deuxieme message"},
    )
    assert second_response["HX-Redirect"] == response["HX-Redirect"]
    with use_tenant(tenant.id):
        assert ChatChannel.objects.filter(tenant=tenant, kind=ChatChannel.KIND_DIRECT).count() == 1


def test_floating_launcher_renders_for_authenticated_user_with_tenant() -> None:
    tenant = Tenant.objects.create(code="UI-CHAT7", name="UI Chat Tenant 7")
    user = User.objects.create_user(email="ui-chat7a@example.com", password="Str0ngPassw0rd!23")
    client = _login_with_tenant(tenant, user)

    soup = BeautifulSoup(client.get("/dashboard/").content, "html.parser")
    assert soup.find("button", class_="wh-fab") is not None


def test_floating_launcher_is_absent_for_anonymous_visitor() -> None:
    client = Client()
    response = client.get("/dashboard/")
    # Non authentifie : redirection vers la connexion, jamais le shell
    # applicatif (donc jamais le bouton flottant).
    assert response.status_code in (302, 403)
