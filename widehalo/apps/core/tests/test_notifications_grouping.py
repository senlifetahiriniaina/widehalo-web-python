from __future__ import annotations

import pytest
from freezegun import freeze_time

from apps.core.models.notification import Notification, WhatsAppMessage
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.notifications import (
    dispatch_notification,
    group_hourly,
    send_whatsapp_notification,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def user_and_tenant():
    tenant = Tenant.objects.create(code="NOTIF-T", name="Notif Tenant")
    user = User.objects.create_user(email="notifme@example.com", password="Str0ngPassw0rd!23")
    return tenant, user


def test_dispatch_notification_creates_a_record(user_and_tenant) -> None:
    tenant, user = user_and_tenant
    notification = dispatch_notification(
        user, "invoice.due", {"amount": 1000}, tenant_id=str(tenant.id)
    )
    assert Notification.objects.filter(pk=notification.pk).exists()
    assert notification.read_at is None


def test_five_notifications_in_the_same_group_produce_a_single_email_batch(user_and_tenant) -> None:
    tenant, user = user_and_tenant
    with freeze_time("2026-01-01 10:00:00"):
        for _ in range(5):
            dispatch_notification(
                user, "stock.low", {}, tenant_id=str(tenant.id), grouped_key="stock.low"
            )
        to_send = group_hourly(user)

    assert len(to_send) == 1


def test_notifications_older_than_the_grouping_window_are_not_grouped_together(
    user_and_tenant,
) -> None:
    tenant, user = user_and_tenant
    with freeze_time("2026-01-01 08:00:00"):
        dispatch_notification(
            user, "stock.low", {}, tenant_id=str(tenant.id), grouped_key="stock.low"
        )

    with freeze_time("2026-01-01 10:00:00"):
        dispatch_notification(
            user, "stock.low", {}, tenant_id=str(tenant.id), grouped_key="stock.low"
        )
        to_send = group_hourly(user)

    # Seule la notification recente (fenetre d'1h) est prise en compte.
    assert len(to_send) == 1


def test_whatsapp_notification_is_stubbed_when_not_configured(user_and_tenant) -> None:
    tenant, user = user_and_tenant
    message = send_whatsapp_notification(
        user, "+261340000000", "order_confirmed", {"body": []}, tenant_id=str(tenant.id)
    )
    assert message.direction == WhatsAppMessage.DIRECTION_OUTBOUND
    # Sans WHATSAPP_ENABLED, le client stub renvoie "stubbed" -> journalise comme "failed"
    # (pas d'envoi reel), pour rester honnete sur l'absence d'integration active.
    assert message.status == WhatsAppMessage.STATUS_FAILED


def test_inbound_whatsapp_webhook_records_a_message(client) -> None:
    import json

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "+261340000000",
                                    "text": {"body": "Bonjour"},
                                    "id": "wamid.abc",
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    response = client.post(
        "/api/v1/notifications/whatsapp/webhook",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json()["processed"] == 1
    assert WhatsAppMessage.objects.filter(provider_message_id="wamid.abc").exists()
