from __future__ import annotations

import pytest
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator

from apps.chat.models import ChatChannel, ChatChannelMembership, ChatMessage
from apps.chat.routing import websocket_urlpatterns
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tenant_context import activate_tenant

application = URLRouter(websocket_urlpatterns)


def _setup_two_tenants_and_channel():
    tenant_a = Tenant.objects.create(code="WS-A", name="WS Tenant A")
    tenant_b = Tenant.objects.create(code="WS-B", name="WS Tenant B")
    alice = User.objects.create_user(email="ws-alice@example.com", password="Str0ngPassw0rd!23")
    mallory = User.objects.create_user(email="ws-mallory@example.com", password="Str0ngPassw0rd!23")
    with activate_tenant(tenant_a.id):
        channel = ChatChannel.objects.create(tenant=tenant_a, kind=ChatChannel.KIND_DIRECT)
        ChatChannelMembership.objects.create(tenant=tenant_a, channel=channel, user=alice)
    return tenant_a, tenant_b, alice, mallory, channel


@pytest.mark.django_db(transaction=True)
async def test_two_members_exchange_messages_in_real_time() -> None:
    tenant_a, _tenant_b, alice, _mallory, channel = await database_sync_to_async(
        _setup_two_tenants_and_channel
    )()
    bob = await database_sync_to_async(
        lambda: User.objects.create_user(email="ws-bob@example.com", password="Str0ngPassw0rd!23")
    )()

    def _add_bob_to_channel() -> None:
        with activate_tenant(tenant_a.id):
            ChatChannelMembership.objects.create(tenant=tenant_a, channel=channel, user=bob)

    await database_sync_to_async(_add_bob_to_channel)()
    with_tenant = str(tenant_a.id)

    alice_comm = WebsocketCommunicator(application, f"/ws/chat/{channel.id}/")
    alice_comm.scope["user"] = alice
    alice_comm.scope["session"] = {"tenant_id": with_tenant}
    bob_comm = WebsocketCommunicator(application, f"/ws/chat/{channel.id}/")
    bob_comm.scope["user"] = bob
    bob_comm.scope["session"] = {"tenant_id": with_tenant}

    connected_a, _ = await alice_comm.connect()
    connected_b, _ = await bob_comm.connect()
    assert connected_a
    assert connected_b

    await alice_comm.send_json_to({"body": "Bonjour Bob"})
    received = await bob_comm.receive_json_from()
    assert received["body"] == "Bonjour Bob"

    await alice_comm.disconnect()
    await bob_comm.disconnect()

    def _read_stored_bodies() -> list[str]:
        with activate_tenant(tenant_a.id):
            return list(ChatMessage.objects.filter(channel=channel).values_list("body", flat=True))

    stored = await database_sync_to_async(_read_stored_bodies)()
    assert "Bonjour Bob" in stored


@pytest.mark.django_db(transaction=True)
async def test_user_from_another_tenant_cannot_join_even_with_forged_channel_id() -> None:
    tenant_a, tenant_b, _alice, mallory, channel = await database_sync_to_async(
        _setup_two_tenants_and_channel
    )()

    communicator = WebsocketCommunicator(application, f"/ws/chat/{channel.id}/")
    communicator.scope["user"] = mallory
    communicator.scope["session"] = {"tenant_id": str(tenant_b.id)}

    connected, _ = await communicator.connect()
    assert not connected


@pytest.mark.django_db(transaction=True)
async def test_user_not_a_member_of_the_channel_is_rejected() -> None:
    tenant_a, _tenant_b, _alice, mallory, channel = await database_sync_to_async(
        _setup_two_tenants_and_channel
    )()

    communicator = WebsocketCommunicator(application, f"/ws/chat/{channel.id}/")
    communicator.scope["user"] = mallory
    communicator.scope["session"] = {"tenant_id": str(tenant_a.id)}

    connected, _ = await communicator.connect()
    assert not connected
