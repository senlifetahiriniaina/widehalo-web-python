"""Tests de `apps.core.services.tenant_backup.run_due_tenant_backups` (BKP3) :
planification due/non due, avancement de `next_run_at` par frequence,
purge de retention (avec dereferencement du `Document` associe)."""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone

from apps.core.models.backup import TenantBackupSchedule, TenantDataOperation
from apps.core.models.document import Document
from apps.core.models.risk import CATEGORY_OTHER, RiskItem
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.tenant_backup import create_tenant_backup, run_due_tenant_backups
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def _create_owner(email: str) -> User:
    return User.objects.create_user(email=email, password="Str0ngPassw0rd!23")


def test_run_due_tenant_backups_only_triggers_due_and_active_schedules() -> None:
    now = timezone.now()

    due_tenant = Tenant.objects.create(code="SCHED-DUE", name="Due")
    with use_tenant(due_tenant.id):
        TenantBackupSchedule.objects.create(
            tenant=due_tenant,
            frequency=TenantBackupSchedule.FREQUENCY_DAILY,
            is_active=True,
            next_run_at=now - datetime.timedelta(hours=1),
        )

    not_due_tenant = Tenant.objects.create(code="SCHED-NOTDUE", name="Not due")
    with use_tenant(not_due_tenant.id):
        TenantBackupSchedule.objects.create(
            tenant=not_due_tenant,
            frequency=TenantBackupSchedule.FREQUENCY_DAILY,
            is_active=True,
            next_run_at=now + datetime.timedelta(hours=1),
        )

    inactive_tenant = Tenant.objects.create(code="SCHED-INACTIVE", name="Inactive")
    with use_tenant(inactive_tenant.id):
        TenantBackupSchedule.objects.create(
            tenant=inactive_tenant,
            frequency=TenantBackupSchedule.FREQUENCY_DAILY,
            is_active=False,
            next_run_at=now - datetime.timedelta(hours=1),
        )

    operations = run_due_tenant_backups()

    triggered_tenant_ids = {operation.tenant_id for operation in operations}
    assert triggered_tenant_ids == {due_tenant.id}
    assert all(
        operation.trigger == TenantDataOperation.TRIGGER_SCHEDULED for operation in operations
    )


@pytest.mark.parametrize(
    "frequency,expected_delta",
    [
        (TenantBackupSchedule.FREQUENCY_DAILY, datetime.timedelta(days=1)),
        (TenantBackupSchedule.FREQUENCY_WEEKLY, datetime.timedelta(weeks=1)),
        (TenantBackupSchedule.FREQUENCY_MONTHLY, datetime.timedelta(days=28)),  # borne basse
    ],
)
def test_next_run_at_advances_by_frequency(frequency: str, expected_delta) -> None:
    now = timezone.now()
    tenant = Tenant.objects.create(code=f"SCHED-{frequency.upper()}", name=frequency)
    with use_tenant(tenant.id):
        schedule = TenantBackupSchedule.objects.create(
            tenant=tenant,
            frequency=frequency,
            is_active=True,
            next_run_at=now - datetime.timedelta(minutes=1),
        )

    run_due_tenant_backups()

    schedule.refresh_from_db()
    assert schedule.last_run_at is not None
    assert schedule.next_run_at >= now + expected_delta - datetime.timedelta(minutes=1)


def test_retention_prunes_oldest_excess_backups_and_dereferences_document() -> None:
    tenant = Tenant.objects.create(code="SCHED-RETAIN", name="Retention")
    owner = _create_owner("owner@retain.test")

    with use_tenant(tenant.id):
        TenantBackupSchedule.objects.create(tenant=tenant, retention_count=1, is_active=True)
        RiskItem.objects.create(
            tenant=tenant, category=CATEGORY_OTHER, likelihood=1, impact=1, score=1, owner=owner
        )
        first = create_tenant_backup(tenant, triggered_by=owner)
        first_document_id = first.document_id

        RiskItem.objects.create(
            tenant=tenant, category=CATEGORY_OTHER, likelihood=2, impact=2, score=4, owner=owner
        )
        second = create_tenant_backup(tenant, triggered_by=owner)

    # retention_count=1 : seule la sauvegarde la plus recente survit.
    backups = TenantDataOperation.all_objects.filter(
        tenant=tenant, operation_type=TenantDataOperation.TYPE_BACKUP
    )
    assert backups.count() == 1
    assert backups.first().id == second.id

    # Le Document de la sauvegarde purgee est dereference (reference_count
    # decremente ; supprime ici puisqu'il n'etait reference qu'une fois).
    assert not Document.all_objects.filter(id=first_document_id).exists()
