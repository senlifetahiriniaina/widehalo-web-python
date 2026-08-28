from __future__ import annotations

import pytest
from django.contrib.auth.models import Group
from freezegun import freeze_time

from apps.core.models.notification import Notification, WhatsAppMessage
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.services.notifications import (
    dispatch_notification,
    group_hourly,
    notify_role,
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


def test_notify_role_notifies_every_member_of_the_role_for_this_tenant(user_and_tenant) -> None:
    tenant, user = user_and_tenant
    other_tenant = Tenant.objects.create(code="NOTIF-T2", name="Autre tenant")
    other_tenant_user = User.objects.create_user(
        email="autretenant@example.com", password="Str0ngPassw0rd!23"
    )
    same_role_other_tenant = User.objects.create_user(
        email="autrerole@example.com", password="Str0ngPassw0rd!23"
    )
    group, _ = Group.objects.get_or_create(name="comptable")
    user.groups.add(group)
    other_tenant_user.groups.add(group)
    same_role_other_tenant.groups.add(group)
    UserTenantMembership.objects.create(user=user, tenant=tenant)
    UserTenantMembership.objects.create(user=other_tenant_user, tenant=tenant)
    UserTenantMembership.objects.create(user=same_role_other_tenant, tenant=other_tenant)

    notifications = notify_role(str(tenant.id), "comptable", "import.needs_qualification", {})

    assert {n.user_id for n in notifications} == {user.id, other_tenant_user.id}


def test_notify_role_returns_empty_list_when_no_member_of_this_role(user_and_tenant) -> None:
    tenant, _user = user_and_tenant
    Group.objects.get_or_create(name="magasinier")

    notifications = notify_role(str(tenant.id), "magasinier", "import.needs_qualification", {})

    assert notifications == []


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
