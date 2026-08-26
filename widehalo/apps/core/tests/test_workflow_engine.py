from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.models.workflow import StateTransitionLog
from apps.core.services.workflow import TransitionPermissionError, attempt_transition
from apps.core.tests.models import SampleTenantScopedRecord
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def record_and_users():
    tenant = Tenant.objects.create(code="WF-T", name="Workflow Tenant")
    author = User.objects.create_user(email="author@example.com", password="Str0ngPassw0rd!23")
    approver = User.objects.create_user(email="approver@example.com", password="Str0ngPassw0rd!23")

    permission = Permission.objects.get(
        codename="approve_sampletenantscopedrecord", content_type__app_label="core"
    )
    group = Group.objects.create(name="wf-approvers")
    group.permissions.add(permission)
    approver.groups.add(group)

    with use_tenant(tenant.id):
        record = SampleTenantScopedRecord.objects.create(
            tenant=tenant, label="demo", created_by=author
        )
    return tenant, author, approver, record


def test_allowed_transition_updates_state_and_logs_it(record_and_users) -> None:
    tenant, author, _approver, record = record_and_users

    with use_tenant(tenant.id):
        attempt_transition(record, "submit", author)
        record.save()

    record.refresh_from_db()
    assert record.state == SampleTenantScopedRecord.STATE_SUBMITTED

    log = StateTransitionLog.objects.get(
        content_type=ContentType.objects.get_for_model(SampleTenantScopedRecord),
        object_id=str(record.pk),
    )
    assert log.from_state == SampleTenantScopedRecord.STATE_DRAFT
    assert log.to_state == SampleTenantScopedRecord.STATE_SUBMITTED
    assert log.was_refused is False


def test_transition_without_permission_is_refused_and_logged(record_and_users) -> None:
    tenant, author, _approver, record = record_and_users

    with use_tenant(tenant.id):
        attempt_transition(record, "submit", author)
        record.save()

        with pytest.raises(TransitionPermissionError):
            attempt_transition(record, "approve", author)

    record.refresh_from_db()
    assert record.state == SampleTenantScopedRecord.STATE_SUBMITTED  # inchange

    refusal = StateTransitionLog.objects.filter(was_refused=True).first()
    assert refusal is not None
    assert refusal.performed_by == author


def test_transition_with_permission_succeeds(record_and_users) -> None:
    tenant, author, approver, record = record_and_users

    with use_tenant(tenant.id):
        attempt_transition(record, "submit", author)
        record.save()

        attempt_transition(record, "approve", approver)
        record.save()

    record.refresh_from_db()
    assert record.state == SampleTenantScopedRecord.STATE_APPROVED
