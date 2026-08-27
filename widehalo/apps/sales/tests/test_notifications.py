"""SAL-NOTIF1 (§5.5.9, S7) : « e-mail automatique a la confirmation, a
l'expedition et a la facturation, plus lien WhatsApp manuel ».

Portee assumee et documentee (cf. docstring
`apps.sales.services.orders._notify_salesperson`) : `dispatch_notification`
ne sait notifier qu'un `User` interne — ce lot notifie donc le COMMERCIAL
de la commande a chaque jalon (pas directement le client final, aucun
canal e-mail-vers-adresse-externe n'existe dans ce socle)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.core.models.notification import Notification
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.sales.services.invoicing import invoice_order
from apps.sales.services.notifications import build_whatsapp_link
from apps.sales.services.orders import add_order_line, confirm_order, create_order, mark_delivered

pytestmark = pytest.mark.django_db


@pytest.fixture
def notif_setup():
    tenant = Tenant.objects.create(code="NOTIF-SAL", name="Notif Sales Tenant")
    salesperson = User.objects.create_user(
        email="commercial-notif@example.com", password="Str0ngPassw0rd!23"
    )
    with use_tenant(tenant.id):
        order = create_order(
            tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today(), salesperson=salesperson
        )
        add_order_line(
            order, description="Article", qty=Decimal(1), unit_price=Decimal(1000), is_custom=True
        )
    return tenant, salesperson, order


def test_confirm_order_notifies_salesperson(notif_setup) -> None:
    tenant, salesperson, order = notif_setup
    with use_tenant(tenant.id):
        confirm_order(order, salesperson)
        notifications = Notification.objects.filter(
            user=salesperson, notification_type="sales.order_confirmed"
        )
    assert notifications.count() == 1


def test_confirm_order_never_notifies_on_blocked_path() -> None:
    """Jamais de notification "confirmee" sur le chemin `blocked` (RG-SAL-4)
    — meme discipline que le RG-SAL-3 heritee de S3 (jamais sur `blocked`)."""
    tenant = Tenant.objects.create(code="NOTIF-BLOCK", name="Notif Blocked Tenant")
    from apps.partners.tests.factories import PartnerFactory

    salesperson = User.objects.create_user(
        email="commercial-blocked@example.com", password="Str0ngPassw0rd!23"
    )
    with use_tenant(tenant.id):
        partner = PartnerFactory(tenant=tenant, credit_limit_mga=Decimal(1))
        order = create_order(
            tenant=tenant, partner_id=partner.id, date=dt.date.today(), salesperson=salesperson
        )
        add_order_line(
            order,
            description="Article cher",
            qty=Decimal(1),
            unit_price=Decimal(1_000_000),
            is_custom=True,
        )
        confirm_order(order, salesperson)
        order.refresh_from_db()
        assert order.state == "blocked"
        notifications = Notification.objects.filter(
            user=salesperson, notification_type="sales.order_confirmed"
        )
    assert notifications.count() == 0


def test_mark_delivered_full_notifies_salesperson(notif_setup) -> None:
    tenant, salesperson, order = notif_setup
    with use_tenant(tenant.id):
        confirm_order(order, salesperson)
        order.refresh_from_db()
        from apps.sales.services.orders import start_preparation

        start_preparation(order, salesperson)
        mark_delivered(order, salesperson, partial=False)
        notifications = Notification.objects.filter(
            user=salesperson, notification_type="sales.order_delivered"
        )
    assert notifications.count() == 1


def test_mark_delivered_partial_does_not_notify_delivered(notif_setup) -> None:
    tenant, salesperson, order = notif_setup
    with use_tenant(tenant.id):
        confirm_order(order, salesperson)
        order.refresh_from_db()
        from apps.sales.services.orders import start_preparation

        start_preparation(order, salesperson)
        mark_delivered(order, salesperson, partial=True)
        notifications = Notification.objects.filter(
            user=salesperson, notification_type="sales.order_delivered"
        )
    assert notifications.count() == 0


def test_invoice_order_notifies_salesperson_on_real_invoice(notif_setup) -> None:
    tenant, salesperson, order = notif_setup
    from apps.accounting.models import AccAccount, AccJournal
    from apps.accounting.tests.factories import (
        AccAccountFactory,
        AccJournalFactory,
        AccPeriodFactory,
    )

    with use_tenant(tenant.id):
        AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_SALE)
        AccPeriodFactory(
            tenant=tenant,
            date_start=dt.date.today().replace(day=1),
            date_end=dt.date.today().replace(day=28),
        )
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_RECEIVABLE)
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_INCOME)

        confirm_order(order, salesperson)
        order.refresh_from_db()
        from apps.sales.services.orders import start_preparation

        start_preparation(order, salesperson)
        mark_delivered(order, salesperson, partial=False)

        move_id = invoice_order(order, salesperson)
        assert move_id is not None

        notifications = Notification.objects.filter(
            user=salesperson, notification_type="sales.order_invoiced"
        )
    assert notifications.count() == 1


def test_build_whatsapp_link_url_encodes_message() -> None:
    link = build_whatsapp_link("+261 34 00 000 00", "Bonjour, voici votre commande & devis")
    assert link is not None
    assert link.startswith("https://wa.me/261340000000?text=")
    assert "%26" in link  # "&" url-encode
    assert " " not in link.split("text=")[1]


def test_build_whatsapp_link_returns_none_without_digits() -> None:
    assert build_whatsapp_link("", "message") is None
    assert build_whatsapp_link("n/a", "message") is None
