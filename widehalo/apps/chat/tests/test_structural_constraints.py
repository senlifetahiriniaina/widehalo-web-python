"""Tests de contraintes structurelles et d'interdependance (T2, CDC §8,
couches 4-5) pour le module `chat`. La RLS est hors perimetre."""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError

from apps.chat.models import ChatChannel, ChatChannelMembership, ChatMessage
from apps.chat.tests.factories import (
    ChatChannelFactory,
    ChatChannelMembershipFactory,
    ChatMessageFactory,
)
from apps.core.models.tenant import Tenant
from apps.core.tests.factories import DocumentFactory, UserFactory
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return Tenant.objects.create(code="CHAT-STRUCT", name="Chat Structural Tenant")


# --- UNIQUE / UniqueConstraint -----------------------------------------------


def test_a_user_cannot_join_the_same_channel_twice(tenant) -> None:
    with use_tenant(tenant.id):
        channel = ChatChannelFactory(tenant=tenant)
        user = UserFactory()
        ChatChannelMembership.objects.create(tenant=tenant, channel=channel, user=user)

        with pytest.raises(IntegrityError), transaction.atomic():
            ChatChannelMembership.objects.create(tenant=tenant, channel=channel, user=user)


# --- on_delete: PROTECT -----------------------------------------------------


def test_deleting_a_tenant_with_chat_rows_is_protected(tenant) -> None:
    with use_tenant(tenant.id):
        ChatChannelFactory(tenant=tenant)

    with pytest.raises(ProtectedError):
        tenant.delete()


# --- on_delete: CASCADE -----------------------------------------------------


def test_deleting_a_channel_cascades_its_memberships(tenant) -> None:
    with use_tenant(tenant.id):
        membership = ChatChannelMembershipFactory(tenant=tenant)
        channel_id = membership.channel_id
        membership_id = membership.id

        ChatChannel.objects.filter(pk=channel_id).delete()

        assert not ChatChannelMembership.objects.filter(pk=membership_id).exists()


def test_deleting_a_channel_cascades_its_messages(tenant) -> None:
    with use_tenant(tenant.id):
        message = ChatMessageFactory(tenant=tenant)
        channel_id = message.channel_id
        message_id = message.id

        ChatChannel.objects.filter(pk=channel_id).delete()

        assert not ChatMessage.objects.filter(pk=message_id).exists()


# --- on_delete: SET_NULL -----------------------------------------------------


def test_deleting_the_sender_sets_message_sender_to_null(tenant) -> None:
    with use_tenant(tenant.id):
        sender = UserFactory()
        message = ChatMessageFactory(tenant=tenant, sender=sender)

        sender.delete()

        message.refresh_from_db()
        assert message.sender_id is None


def test_deleting_the_attachment_document_sets_message_attachment_to_null(tenant) -> None:
    with use_tenant(tenant.id):
        document = DocumentFactory(tenant=tenant)
        message = ChatMessageFactory(tenant=tenant, attachment=document)

        document.delete()

        message.refresh_from_db()
        assert message.attachment_id is None
