"""WA-6/WA-8 (cahier Phase 2 §13.4) : traitement gouverné d'un message
entrant — chatter + menu d'intentions borné."""

from __future__ import annotations

import pytest

from apps.chat.models import ChatChannel
from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.whatsapp.models import WaConversation, WaMessageTemplate
from apps.whatsapp.services.inbound import MENU_TEMPLATE_CODE, handle_inbound_message
from apps.whatsapp.services.templates import approve_template, create_template, submit_for_review

pytestmark = pytest.mark.django_db


def _approve_menu_template(tenant) -> WaMessageTemplate:
    reviewer = UserFactory()
    template = create_template(
        tenant,
        code=MENU_TEMPLATE_CODE,
        name="Menu principal",
        category=WaMessageTemplate.CATEGORY_UTILITY,
        body_text="1. Support / 2. Commande / 3. Parler à un humain",
    )
    submit_for_review(template)
    approve_template(template, user=reviewer)
    return template


def test_handle_inbound_message_creates_conversation_and_opens_chatter_channel() -> None:
    tenant = Tenant.objects.create(code="WA-I1", name="WhatsApp Inbound Tenant 1")
    with use_tenant(tenant.id):
        conversation = handle_inbound_message(tenant, phone_number="+261340000020", body="Bonjour")

        assert conversation.last_inbound_at is not None
        assert conversation.chat_channel_id != ""
        assert ChatChannel.objects.filter(id=conversation.chat_channel_id).exists()


def test_handle_inbound_message_reuses_existing_conversation_and_channel() -> None:
    tenant = Tenant.objects.create(code="WA-I2", name="WhatsApp Inbound Tenant 2")
    with use_tenant(tenant.id):
        first = handle_inbound_message(tenant, phone_number="+261340000021", body="Bonjour")
        channel_id = first.chat_channel_id

        second = handle_inbound_message(tenant, phone_number="+261340000021", body="Encore moi")

        assert second.id == first.id
        assert second.chat_channel_id == channel_id
        assert (
            WaConversation.objects.filter(tenant=tenant, phone_number="+261340000021").count() == 1
        )


def test_first_contact_without_approved_menu_template_sends_no_reply() -> None:
    """Simplification disclosed : un tenant qui n'a pas encore configuré/
    approuvé son modèle de menu ne reçoit aucune relance automatique."""
    tenant = Tenant.objects.create(code="WA-I3", name="WhatsApp Inbound Tenant 3")
    with use_tenant(tenant.id):
        conversation = handle_inbound_message(tenant, phone_number="+261340000022", body="Bonjour")
        assert conversation.intent_state == WaConversation.INTENT_NONE


def test_first_contact_with_approved_menu_template_sends_menu_once() -> None:
    tenant = Tenant.objects.create(code="WA-I4", name="WhatsApp Inbound Tenant 4")
    with use_tenant(tenant.id):
        _approve_menu_template(tenant)

        conversation = handle_inbound_message(tenant, phone_number="+261340000023", body="Bonjour")
        assert conversation.intent_state == WaConversation.INTENT_MENU_SENT

        # Un second message entrant ne relance pas indefiniment le menu.
        conversation = handle_inbound_message(
            tenant, phone_number="+261340000023", body="Toujours la"
        )
        assert conversation.intent_state == WaConversation.INTENT_MENU_SENT


def test_intent_choice_1_transitions_to_awaiting_human() -> None:
    tenant = Tenant.objects.create(code="WA-I5", name="WhatsApp Inbound Tenant 5")
    with use_tenant(tenant.id):
        _approve_menu_template(tenant)
        handle_inbound_message(tenant, phone_number="+261340000024", body="Bonjour")

        conversation = handle_inbound_message(tenant, phone_number="+261340000024", body="1")
        assert conversation.intent_state == WaConversation.INTENT_AWAITING_HUMAN


def test_intent_choice_2_transitions_to_resolved() -> None:
    tenant = Tenant.objects.create(code="WA-I6", name="WhatsApp Inbound Tenant 6")
    with use_tenant(tenant.id):
        _approve_menu_template(tenant)
        handle_inbound_message(tenant, phone_number="+261340000025", body="Bonjour")

        conversation = handle_inbound_message(tenant, phone_number="+261340000025", body="2")
        assert conversation.intent_state == WaConversation.INTENT_RESOLVED


def test_unknown_reply_does_not_change_intent_state() -> None:
    tenant = Tenant.objects.create(code="WA-I7", name="WhatsApp Inbound Tenant 7")
    with use_tenant(tenant.id):
        _approve_menu_template(tenant)
        handle_inbound_message(tenant, phone_number="+261340000026", body="Bonjour")

        conversation = handle_inbound_message(
            tenant, phone_number="+261340000026", body="njamais vu"
        )
        assert conversation.intent_state == WaConversation.INTENT_MENU_SENT
