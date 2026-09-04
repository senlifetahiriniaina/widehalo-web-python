"""Bloc D, D3 (QUA-9) : commande de management `run_quality_control_checks`
— boucle tous tenants, aucune fuite inter-tenant. Calque direct de
`apps/purchase/tests/test_price_watch_command.py`."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.utils import timezone

from apps.core.models.notification import Notification
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.tests.utils import use_tenant
from apps.quality.services.control_plans import add_critical_point, create_control_plan
from apps.quality.services.measurements import record_measurement
from apps.stocks.tests.factories import StkLotFactory

pytestmark = pytest.mark.django_db


def _setup_overdue_lot(tenant: Tenant, *, lot_name: str) -> None:
    with use_tenant(tenant.id):
        measurer = User.objects.create_user(
            email=f"mesureur-{tenant.code}@example.com", password="Str0ngPassw0rd!23"
        )
        notified = User.objects.create_user(
            email=f"resp-{tenant.code}@example.com", password="Str0ngPassw0rd!23"
        )
        group, _created = Group.objects.get_or_create(name="resp_production")
        notified.groups.add(group)
        UserTenantMembership.objects.create(user=notified, tenant=tenant)

        plan = create_control_plan(tenant=tenant, name="Cuisson", frequency_days=7)
        point = add_critical_point(plan, name="Température", limit_min=Decimal(70))
        lot = StkLotFactory(tenant=tenant, name=lot_name)
        record_measurement(
            point,
            tenant=tenant,
            value=Decimal(80),
            measured_by=measurer,
            lot_variant_id=lot.variant_id,
            lot_name=lot.name,
            measured_at=timezone.now() - timedelta(days=30),
        )


def test_run_quality_control_checks_command_notifies_overdue_lot() -> None:
    tenant = Tenant.objects.create(code="QLT-CMD", name="Quality Command Tenant")
    _setup_overdue_lot(tenant, lot_name="LOT-CMD-001")

    call_command("run_quality_control_checks")

    assert Notification.objects.filter(
        tenant_id=tenant.id, notification_type="quality.control_overdue"
    ).exists()


def test_run_quality_control_checks_command_isolates_tenants() -> None:
    """`Notification.tenant_id` est un `UUIDField` nu (pas une FK scopée
    par `use_tenant`) — l'isolation est vérifiée en filtrant explicitement
    par `tenant_id`, pas via le contexte tenant courant."""
    tenant_a = Tenant.objects.create(code="QLT-CMD-A", name="Quality Command Tenant A")
    tenant_b = Tenant.objects.create(code="QLT-CMD-B", name="Quality Command Tenant B")
    _setup_overdue_lot(tenant_a, lot_name="LOT-CMD-A-001")

    call_command("run_quality_control_checks")

    assert Notification.objects.filter(
        tenant_id=tenant_a.id, notification_type="quality.control_overdue"
    ).exists()
    assert not Notification.objects.filter(
        tenant_id=tenant_b.id, notification_type="quality.control_overdue"
    ).exists()


def test_run_quality_control_checks_command_no_op_without_plans() -> None:
    Tenant.objects.create(code="QLT-CMD-EMPTY", name="Quality Command No Plans")
    # Ne doit pas lever malgré l'absence de plan de contrôle.
    call_command("run_quality_control_checks")
