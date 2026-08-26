from __future__ import annotations

import pytest
from django.db import DatabaseError, connection

from apps.core.models.audit import AuditLog
from apps.core.models.tenant import Tenant
from apps.core.tests.models import SampleTenantScopedRecord
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def test_raw_sql_update_on_audit_log_is_rejected() -> None:
    log = AuditLog.objects.create(action="manual-test")
    with pytest.raises(DatabaseError, match="immuable"), connection.cursor() as cursor:
        cursor.execute("UPDATE core_audit_log SET action = %s WHERE id = %s", ["hacked", log.id])


def test_raw_sql_delete_on_audit_log_is_rejected() -> None:
    log = AuditLog.objects.create(action="manual-test-2")
    with pytest.raises(DatabaseError, match="immuable"), connection.cursor() as cursor:
        cursor.execute("DELETE FROM core_audit_log WHERE id = %s", [log.id])


def test_orm_save_of_audit_log_also_fails() -> None:
    log = AuditLog.objects.create(action="manual-test-3")
    log.action = "changed"
    with pytest.raises(DatabaseError, match="immuable"):
        log.save(update_fields=["action"])


def test_creating_a_base_model_entity_is_logged_automatically() -> None:
    tenant = Tenant.objects.create(code="AUDIT-T", name="Audit Tenant")
    with use_tenant(tenant.id):
        record = SampleTenantScopedRecord.objects.create(tenant=tenant, label="x")

    from django.contrib.contenttypes.models import ContentType

    log = AuditLog.objects.filter(
        action=AuditLog.ACTION_CREATED,
        content_type=ContentType.objects.get_for_model(SampleTenantScopedRecord),
        object_id=str(record.pk),
    ).first()
    assert log is not None
