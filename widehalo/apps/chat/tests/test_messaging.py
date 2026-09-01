from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.chat.models import ChatChannel, ChatChannelMembership, ChatMessage
from apps.chat.services.messaging import (
    MAX_ATTACHMENT_SIZE,
    get_or_create_direct_channel,
    is_channel_member,
    post_message,
)
from apps.chat.services.public import get_or_create_document_channel
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.models import SampleTenantScopedRecord
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant_and_users():
    tenant = Tenant.objects.create(code="CHAT-T", name="Chat Tenant")
    alice = User.objects.create_user(email="alice@example.com", password="Str0ngPassw0rd!23")
    bob = User.objects.create_user(email="bob@example.com", password="Str0ngPassw0rd!23")
    return tenant, alice, bob


def test_post_message_creates_a_message_and_publishes_event(tenant_and_users) -> None:
    tenant, alice, _bob = tenant_and_users
    with use_tenant(tenant.id):
        channel = ChatChannel.objects.create(tenant=tenant, kind=ChatChannel.KIND_DIRECT)
        ChatChannelMembership.objects.create(tenant=tenant, channel=channel, user=alice)

        message = post_message(channel=channel, sender=alice, body="Bonjour")

        assert ChatMessage.objects.filter(pk=message.pk).exists()
        assert message.body == "Bonjour"


def test_attachment_over_25mb_is_rejected(tenant_and_users) -> None:
    tenant, alice, _bob = tenant_and_users
    with use_tenant(tenant.id):
        channel = ChatChannel.objects.create(tenant=tenant, kind=ChatChannel.KIND_DIRECT)
        ChatChannelMembership.objects.create(tenant=tenant, channel=channel, user=alice)

        oversized = SimpleUploadedFile(
            "big.bin", b"x" * (MAX_ATTACHMENT_SIZE + 1), content_type="application/octet-stream"
        )

        with pytest.raises(ValidationError):
            post_message(channel=channel, sender=alice, body="", attachment_file=oversized)


def test_get_or_create_document_channel_is_idempotent(tenant_and_users) -> None:
    tenant, alice, bob = tenant_and_users
    with use_tenant(tenant.id):
        record = SampleTenantScopedRecord.objects.create(tenant=tenant, label="DOC-2026-0001")

        channel_id_1 = get_or_create_document_channel(
            tenant=tenant, content_object=record, participants=[alice]
        )
        channel_id_2 = get_or_create_document_channel(
            tenant=tenant, content_object=record, participants=[bob]
        )

        assert channel_id_1 == channel_id_2
        channel = ChatChannel.objects.get(id=channel_id_1)
        assert is_channel_member(channel, alice)
        assert is_channel_member(channel, bob)


def test_get_or_create_direct_channel_is_idempotent(tenant_and_users) -> None:
    """Correctif de bug reel (UXR2) : `get_or_create_direct_channel`
    retrouve desormais le canal direct existant entre les 2 memes
    participants au lieu d'en creer un nouveau a chaque appel — sinon
    chaque « nouvelle conversation » avec la meme personne creerait un
    doublon (cf. `get_or_create_document_channel`, qui applique deja cette
    discipline de recherche prealable)."""
    tenant, alice, bob = tenant_and_users
    with use_tenant(tenant.id):
        channel_1 = get_or_create_direct_channel(tenant=tenant, participants=[alice, bob])
        channel_2 = get_or_create_direct_channel(tenant=tenant, participants=[alice, bob])

        assert channel_1.id == channel_2.id
        assert ChatChannel.objects.filter(tenant=tenant, kind=ChatChannel.KIND_DIRECT).count() == 1
        member_ids = set(
            ChatChannelMembership.objects.filter(channel=channel_1).values_list(
                "user_id", flat=True
            )
        )
        assert member_ids == {alice.id, bob.id}


def test_get_or_create_direct_channel_participant_order_does_not_matter(tenant_and_users) -> None:
    tenant, alice, bob = tenant_and_users
    with use_tenant(tenant.id):
        channel_1 = get_or_create_direct_channel(tenant=tenant, participants=[alice, bob])
        channel_2 = get_or_create_direct_channel(tenant=tenant, participants=[bob, alice])

        assert channel_1.id == channel_2.id


def test_get_or_create_direct_channel_distinct_pair_gets_its_own_channel(
    tenant_and_users,
) -> None:
    tenant, alice, bob = tenant_and_users
    with use_tenant(tenant.id):
        carol = User.objects.create_user(email="carol@example.com", password="Str0ngPassw0rd!23")

        channel_ab = get_or_create_direct_channel(tenant=tenant, participants=[alice, bob])
        channel_ac = get_or_create_direct_channel(tenant=tenant, participants=[alice, carol])

        assert channel_ab.id != channel_ac.id
        assert ChatChannel.objects.filter(tenant=tenant, kind=ChatChannel.KIND_DIRECT).count() == 2


def test_non_member_is_not_a_channel_member(tenant_and_users) -> None:
    tenant, alice, bob = tenant_and_users
    with use_tenant(tenant.id):
        channel = ChatChannel.objects.create(tenant=tenant, kind=ChatChannel.KIND_DIRECT)
        ChatChannelMembership.objects.create(tenant=tenant, channel=channel, user=alice)

        assert not is_channel_member(channel, bob)
