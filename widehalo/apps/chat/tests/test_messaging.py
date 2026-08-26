from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.chat.models import ChatChannel, ChatChannelMembership, ChatMessage
from apps.chat.services.messaging import (
    MAX_ATTACHMENT_SIZE,
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


def test_non_member_is_not_a_channel_member(tenant_and_users) -> None:
    tenant, alice, bob = tenant_and_users
    with use_tenant(tenant.id):
        channel = ChatChannel.objects.create(tenant=tenant, kind=ChatChannel.KIND_DIRECT)
        ChatChannelMembership.objects.create(tenant=tenant, channel=channel, user=alice)

        assert not is_channel_member(channel, bob)
