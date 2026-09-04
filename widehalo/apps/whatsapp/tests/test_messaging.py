"""WA-1/WA-3/WA-5/WA-7 (cahier Phase 2 §13.4) : envoi gouverné (3
garde-fous) et reprise dédiée des envois en échec."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.notification import WhatsAppMessage
from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.whatsapp.models import WaMessageTemplate
from apps.whatsapp.services.consent import grant_consent
from apps.whatsapp.services.messaging import (
    MAX_RETRY_ATTEMPTS,
    retry_failed_messages,
    send_governed_template_message,
)
from apps.whatsapp.services.templates import approve_template, create_template, submit_for_review

pytestmark = pytest.mark.django_db


@dataclass
class _FakeSendResult:
    status: str
    provider_message_id: str = ""
    details: str = ""


class _FakeSucceedingClient:
    def send_template(self, phone_number, template_name, params):
        return _FakeSendResult(status="sent", provider_message_id="wamid.fake")


class _FakeFailingClient:
    def send_template(self, phone_number, template_name, params):
        return _FakeSendResult(status="failed", details="boom")


def _approved_template(tenant, *, code="promo", cost=Decimal("50")):
    reviewer = UserFactory()
    template = create_template(
        tenant,
        code=code,
        name="Promo",
        category=WaMessageTemplate.CATEGORY_MARKETING,
        body_text="Bonjour {{nom_client}}",
        variables=["nom_client"],
        estimated_cost_ariary=cost,
    )
    submit_for_review(template)
    approve_template(template, user=reviewer)
    return template


def test_send_rejects_unapproved_template() -> None:
    tenant = Tenant.objects.create(code="WA-M1", name="WhatsApp Messaging Tenant 1")
    with use_tenant(tenant.id):
        user = UserFactory()
        grant_consent(tenant, phone_number="+261340000010", source="formulaire_web")
        with pytest.raises(ValidationError):
            send_governed_template_message(
                tenant,
                phone_number="+261340000010",
                template_code="inconnu",
                variables={},
                user=user,
            )


def test_send_rejects_missing_consent() -> None:
    tenant = Tenant.objects.create(code="WA-M2", name="WhatsApp Messaging Tenant 2")
    with use_tenant(tenant.id):
        user = UserFactory()
        _approved_template(tenant)
        with pytest.raises(ValidationError):
            send_governed_template_message(
                tenant,
                phone_number="+261340000011",
                template_code="promo",
                variables={"nom_client": "Rina"},
                user=user,
            )


def test_send_rejects_when_budget_exceeded() -> None:
    tenant = Tenant.objects.create(code="WA-M3", name="WhatsApp Messaging Tenant 3")
    tenant.whatsapp_monthly_cost_cap_ariary = Decimal("10")
    tenant.save(update_fields=["whatsapp_monthly_cost_cap_ariary"])
    with use_tenant(tenant.id):
        user = UserFactory()
        grant_consent(tenant, phone_number="+261340000012", source="formulaire_web")
        _approved_template(tenant, cost=Decimal("50"))
        with pytest.raises(ValidationError):
            send_governed_template_message(
                tenant,
                phone_number="+261340000012",
                template_code="promo",
                variables={"nom_client": "Rina"},
                user=user,
            )


def test_send_success_updates_message_and_conversation(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.core.services.notifications.get_whatsapp_client", lambda: _FakeSucceedingClient()
    )
    tenant = Tenant.objects.create(code="WA-M4", name="WhatsApp Messaging Tenant 4")
    with use_tenant(tenant.id):
        user = UserFactory()
        grant_consent(tenant, phone_number="+261340000013", source="formulaire_web")
        _approved_template(tenant, cost=Decimal("50"))

        message = send_governed_template_message(
            tenant,
            phone_number="+261340000013",
            template_code="promo",
            variables={"nom_client": "Rina"},
            user=user,
        )

        assert message.status == WhatsAppMessage.STATUS_SENT
        assert message.cost_ariary == Decimal("50")
        assert message.category == WaMessageTemplate.CATEGORY_MARKETING
        assert message.body == "Bonjour Rina"
        assert message.conversation_id is not None


def test_retry_failed_messages_succeeds_and_updates_status(monkeypatch) -> None:
    tenant = Tenant.objects.create(code="WA-M5", name="WhatsApp Messaging Tenant 5")
    with use_tenant(tenant.id):
        failed = WhatsAppMessage.objects.create(
            tenant_id=tenant.id,
            direction=WhatsAppMessage.DIRECTION_OUTBOUND,
            phone_number="+261340000014",
            template_name="promo",
            status=WhatsAppMessage.STATUS_FAILED,
        )
        monkeypatch.setattr(
            "apps.core.services.whatsapp.get_whatsapp_client", lambda: _FakeSucceedingClient()
        )
        retried = retry_failed_messages(tenant)

        assert len(retried) == 1
        failed.refresh_from_db()
        assert failed.status == WhatsAppMessage.STATUS_SENT
        assert failed.retry_count == 1
        assert failed.next_retry_at is None


def test_retry_failed_messages_stops_after_max_attempts(monkeypatch) -> None:
    tenant = Tenant.objects.create(code="WA-M6", name="WhatsApp Messaging Tenant 6")
    with use_tenant(tenant.id):
        failed = WhatsAppMessage.objects.create(
            tenant_id=tenant.id,
            direction=WhatsAppMessage.DIRECTION_OUTBOUND,
            phone_number="+261340000015",
            template_name="promo",
            status=WhatsAppMessage.STATUS_FAILED,
            retry_count=MAX_RETRY_ATTEMPTS,
        )
        monkeypatch.setattr(
            "apps.core.services.whatsapp.get_whatsapp_client", lambda: _FakeFailingClient()
        )
        retried = retry_failed_messages(tenant)

        assert retried == []
        failed.refresh_from_db()
        assert failed.retry_count == MAX_RETRY_ATTEMPTS
        assert failed.status == WhatsAppMessage.STATUS_FAILED
