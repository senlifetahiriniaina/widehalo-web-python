"""INT1 (chantier interactivite native inter-modules) : gap de notification
identifie par lecture directe — `SalesOrder.state == blocked` (RG-SAL-4)
n'avait aucune notification/evenement, contrairement a
`confirm_order`/`mark_delivered` (SAL-NOTIF1, S7)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.core.models.event import EventLog
from apps.core.models.notification import Notification
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.partners.tests.factories import PartnerFactory
from apps.sales.models import SalesOrder
from apps.sales.services.orders import add_order_line, confirm_order, create_order

pytestmark = pytest.mark.django_db


@pytest.fixture
def orders_setup():
    tenant = Tenant.objects.create(code="SALES-INT1-ORD", name="Sales INT1 Orders Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="sales-int1-ord@example.com", password="Str0ngPassw0rd!23"
        )
        partner = PartnerFactory(tenant=tenant)
        return tenant, user, partner


def test_confirm_order_over_credit_limit_publishes_order_blocked(orders_setup) -> None:
    tenant, user, _partner = orders_setup
    with use_tenant(tenant.id):
        partner = PartnerFactory(tenant=tenant, credit_limit_mga=Decimal("5000"))
        order = create_order(
            tenant=tenant, partner_id=partner.id, date=dt.date.today(), salesperson=user
        )
        add_order_line(
            order, description="Article", qty=Decimal(1), unit_price=Decimal(10000), is_custom=True
        )
        blocked = confirm_order(order, user)
        assert blocked.state == SalesOrder.STATE_BLOCKED

    event = EventLog.objects.get(event_type="sales.order_blocked", tenant_id=str(tenant.id))
    assert event.payload["order_id"] == str(blocked.id)
    assert event.payload["partner_id"] == str(partner.id)
    assert Notification.objects.filter(user=user, notification_type="sales.order_blocked").exists()


def test_confirm_order_within_credit_limit_does_not_publish_order_blocked(orders_setup) -> None:
    tenant, user, partner = orders_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        add_order_line(
            order, description="Article", qty=Decimal(1), unit_price=Decimal(1000), is_custom=True
        )
        confirm_order(order, user)

    assert not EventLog.objects.filter(
        event_type="sales.order_blocked", tenant_id=str(tenant.id)
    ).exists()
