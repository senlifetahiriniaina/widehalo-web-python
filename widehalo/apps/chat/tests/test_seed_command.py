"""Test leger de `seed_chat` (T10) : verifie que la commande produit un
canal avec membres et messages, et qu'une relance ne duplique rien."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.chat.models import ChatChannel, ChatMessage
from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant

pytestmark = pytest.mark.django_db


def test_seed_chat_creates_coherent_demo_dataset() -> None:
    call_command("seed_chat", "--tenant-code=SEEDCHAT")

    tenant = Tenant.objects.get(code="SEEDCHAT")
    with activate_tenant(tenant.id):
        channel = ChatChannel.objects.get(tenant=tenant)
        assert channel.memberships.count() == 2
        assert channel.messages.count() == 2


def test_seed_chat_is_idempotent() -> None:
    call_command("seed_chat", "--tenant-code=SEEDCHAT2")
    call_command("seed_chat", "--tenant-code=SEEDCHAT2")

    tenant = Tenant.objects.get(code="SEEDCHAT2")
    with activate_tenant(tenant.id):
        assert ChatChannel.objects.filter(tenant=tenant).count() == 1
        assert ChatMessage.objects.filter(tenant=tenant).count() == 2
