from __future__ import annotations

import pytest
from django.test import Client

from apps.chat.models import ChatChannel, ChatChannelMembership
from apps.chat.services.messaging import post_message
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def _access_token(client: Client, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        {"email": email, "password": password},
        content_type="application/json",
    )
    return response.json()["access"]


def _headers(token: str, tenant_id: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": tenant_id}


@pytest.fixture
def chat_fixture():
    tenant = Tenant.objects.create(code="CHAT-API", name="Chat API Tenant")
    alice = User.objects.create_user(email="alice-api@example.com", password="Str0ngPassw0rd!23")
    bob = User.objects.create_user(email="bob-api@example.com", password="Str0ngPassw0rd!23")
    with use_tenant(tenant.id):
        channel = ChatChannel.objects.create(tenant=tenant, kind=ChatChannel.KIND_DIRECT)
        ChatChannelMembership.objects.create(tenant=tenant, channel=channel, user=alice)
    return tenant, alice, bob, channel


def test_member_can_list_messages(chat_fixture) -> None:
    tenant, alice, _bob, channel = chat_fixture
    with use_tenant(tenant.id):
        post_message(channel=channel, sender=alice, body="Salut")

    client = Client()
    token = _access_token(client, alice.email, "Str0ngPassw0rd!23")
    response = client.get(
        f"/api/v1/chat/channels/{channel.id}/messages", **_headers(token, str(tenant.id))
    )
    assert response.status_code == 200
    assert response.json()["results"][0]["body"] == "Salut"


def test_polling_since_returns_only_new_messages(chat_fixture) -> None:
    tenant, alice, _bob, channel = chat_fixture
    with use_tenant(tenant.id):
        first = post_message(channel=channel, sender=alice, body="Un")
        post_message(channel=channel, sender=alice, body="Deux")

    client = Client()
    token = _access_token(client, alice.email, "Str0ngPassw0rd!23")
    response = client.get(
        f"/api/v1/chat/channels/{channel.id}/messages",
        {"since": str(first.id)},
        **_headers(token, str(tenant.id)),
    )
    bodies = [m["body"] for m in response.json()["results"]]
    assert bodies == ["Deux"]


def test_non_member_cannot_read_channel_messages(chat_fixture) -> None:
    tenant, _alice, bob, channel = chat_fixture
    client = Client()
    token = _access_token(client, bob.email, "Str0ngPassw0rd!23")
    response = client.get(
        f"/api/v1/chat/channels/{channel.id}/messages", **_headers(token, str(tenant.id))
    )
    assert response.status_code == 403


def test_member_can_post_a_message_via_http(chat_fixture) -> None:
    tenant, alice, _bob, channel = chat_fixture
    client = Client()
    token = _access_token(client, alice.email, "Str0ngPassw0rd!23")
    response = client.post(
        f"/api/v1/chat/channels/{channel.id}/messages",
        {"body": "Envoye par HTTP (repli polling)"},
        **_headers(token, str(tenant.id)),
    )
    assert response.status_code == 200
    assert response.json()["body"] == "Envoye par HTTP (repli polling)"
