"""Bloc F, F4 (FOR-15) : commande de management `run_expiry_alerts` —
boucle tous tenants, aucune fuite inter-tenant. Calque direct de
`apps/quality/tests/test_run_quality_control_checks_command.py`."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command

from apps.core.models.notification import Notification
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.tests.utils import use_tenant
from apps.stocks.tests.factories import StkLotFactory, StkQuantFactory

pytestmark = pytest.mark.django_db


def _setup_expiring_lot(tenant: Tenant, *, lot_name: str) -> None:
    with use_tenant(tenant.id):
        notified = User.objects.create_user(
            email=f"magasinier-{tenant.code}@example.com", password="Str0ngPassw0rd!23"
        )
        group, _created = Group.objects.get_or_create(name="magasinier")
        notified.groups.add(group)
        UserTenantMembership.objects.create(user=notified, tenant=tenant)

        lot = StkLotFactory(
            tenant=tenant, name=lot_name, date_expiry=dt.date.today() + dt.timedelta(days=1)
        )
        StkQuantFactory(tenant=tenant, variant_id=lot.variant_id, lot=lot, qty=Decimal(5))


def test_run_expiry_alerts_command_notifies_expiring_lot() -> None:
    tenant = Tenant.objects.create(code="STK-EXP-CMD", name="Stocks Expiry Command Tenant")
    _setup_expiring_lot(tenant, lot_name="LOT-CMD-001")

    call_command("run_expiry_alerts")

    assert Notification.objects.filter(
        tenant_id=tenant.id, notification_type="stocks.lot_expiring"
    ).exists()


def test_run_expiry_alerts_command_isolates_tenants() -> None:
    """`Notification.tenant_id` est un `UUIDField` nu (pas une FK scopée
    par `use_tenant`) — l'isolation est vérifiée en filtrant explicitement
    par `tenant_id`, pas via le contexte tenant courant."""
    tenant_a = Tenant.objects.create(code="STK-EXP-CMD-A", name="Stocks Expiry Command Tenant A")
    tenant_b = Tenant.objects.create(code="STK-EXP-CMD-B", name="Stocks Expiry Command Tenant B")
    _setup_expiring_lot(tenant_a, lot_name="LOT-CMD-A-001")

    call_command("run_expiry_alerts")

    assert Notification.objects.filter(
        tenant_id=tenant_a.id, notification_type="stocks.lot_expiring"
    ).exists()
    assert not Notification.objects.filter(
        tenant_id=tenant_b.id, notification_type="stocks.lot_expiring"
    ).exists()


def test_run_expiry_alerts_command_no_op_without_lots() -> None:
    Tenant.objects.create(code="STK-EXP-CMD-EMPTY", name="Stocks Expiry Command No Lots")
    # Ne doit pas lever malgré l'absence de lot.
    call_command("run_expiry_alerts")
