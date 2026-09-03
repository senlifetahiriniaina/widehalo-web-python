"""Cahier des charges WideHalo v3, Phase 1, §9 (« Serveur d'envoi
d'e-mail »). Ecart confirme par l'audit
(docs/audit/2026-09-cahier-des-charges-v3-audit.md, §9) : le canal e-mail
des notifications etait du code mort (`email_sent_at` marque sans jamais
appeler `send_mail`) — corrige par
`apps.core.services.notifications.send_grouped_email_notifications` et la
commande `send_grouped_notification_emails`."""

from __future__ import annotations

import pytest
from django.core import mail
from django.core.management import call_command

from apps.core.models.notification import Notification
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.notifications import (
    dispatch_notification,
    send_grouped_email_notifications,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def user_and_tenant():
    tenant = Tenant.objects.create(code="MAIL-T", name="Mail Tenant")
    user = User.objects.create_user(email="mailme@example.com", password="Str0ngPassw0rd!23")
    return tenant, user


def test_send_grouped_email_notifications_actually_sends_an_email(user_and_tenant) -> None:
    tenant, user = user_and_tenant
    dispatch_notification(
        user,
        "sales.order_delivered",
        {"message": "La commande DEV-1 a été livrée.", "action_url": "/sales/orders/1/", "action_label": "Voir la commande"},
        tenant_id=str(tenant.id),
        grouped_key="sales.order_delivered",
    )

    sent_count = send_grouped_email_notifications(user)

    assert sent_count == 1
    assert len(mail.outbox) == 1
    email = mail.outbox[0]
    assert email.to == [user.email]
    assert "La commande DEV-1 a été livrée." in email.body
    assert "/sales/orders/1/" in email.body


def test_send_grouped_email_notifications_sends_nothing_when_no_pending_notification(
    user_and_tenant,
) -> None:
    _tenant, user = user_and_tenant

    sent_count = send_grouped_email_notifications(user)

    assert sent_count == 0
    assert len(mail.outbox) == 0


def test_five_notifications_in_the_same_group_produce_a_single_email(user_and_tenant) -> None:
    tenant, user = user_and_tenant
    for i in range(5):
        dispatch_notification(
            user, "stock.low", {"message": f"Rupture {i}"}, tenant_id=str(tenant.id), grouped_key="stock.low"
        )

    sent_count = send_grouped_email_notifications(user)

    assert sent_count == 1
    assert len(mail.outbox) == 1


def test_management_command_emails_every_user_with_pending_notifications(user_and_tenant) -> None:
    tenant, user = user_and_tenant
    other_user = User.objects.create_user(email="autre@example.com", password="Str0ngPassw0rd!23")
    dispatch_notification(user, "invoice.due", {"message": "Facture échue"}, tenant_id=str(tenant.id))
    dispatch_notification(
        other_user, "invoice.due", {"message": "Facture échue"}, tenant_id=str(tenant.id)
    )
    # Utilisateur sans notification en attente : ne doit produire aucun e-mail.
    User.objects.create_user(email="silencieux@example.com", password="Str0ngPassw0rd!23")

    call_command("send_grouped_notification_emails")

    assert len(mail.outbox) == 2
    recipients = {email.to[0] for email in mail.outbox}
    assert recipients == {user.email, other_user.email}


def test_already_emailed_notification_is_not_sent_twice(user_and_tenant) -> None:
    tenant, user = user_and_tenant
    dispatch_notification(user, "invoice.due", {"message": "Facture échue"}, tenant_id=str(tenant.id))

    first = send_grouped_email_notifications(user)
    second = send_grouped_email_notifications(user)

    assert first == 1
    assert second == 0
    assert len(mail.outbox) == 1


def test_notification_model_email_sent_at_is_populated() -> None:
    tenant = Tenant.objects.create(code="MAIL-T2", name="Mail Tenant 2")
    user = User.objects.create_user(email="checkflag@example.com", password="Str0ngPassw0rd!23")
    notification = dispatch_notification(
        user, "invoice.due", {"message": "Facture échue"}, tenant_id=str(tenant.id)
    )

    send_grouped_email_notifications(user)

    notification.refresh_from_db()
    assert notification.email_sent_at is not None
    assert Notification.objects.filter(pk=notification.pk, email_sent_at__isnull=False).exists()
