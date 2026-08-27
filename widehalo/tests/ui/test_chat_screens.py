from __future__ import annotations

import pytest
from apps.chat.models import ChatChannel, ChatChannelMembership, ChatMessage
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
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
