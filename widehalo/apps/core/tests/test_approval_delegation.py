from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.models.workflow import ApprovalRequest, ApprovalRule
from apps.core.services import approvals
from apps.core.tests.models import SampleTenantScopedRecord
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup():
    tenant = Tenant.objects.create(code="APR-T", name="Approval Tenant")
    author = User.objects.create_user(email="author2@example.com", password="Str0ngPassw0rd!23")
    primary = User.objects.create_user(email="primary@example.com", password="Str0ngPassw0rd!23")
    backup = User.objects.create_user(email="backup@example.com", password="Str0ngPassw0rd!23")

    primary.groups.add(Group.objects.create(name="resp_commercial"))
    backup.groups.add(Group.objects.create(name="direction"))

    with use_tenant(tenant.id):
        record = SampleTenantScopedRecord.objects.create(
            tenant=tenant, label="x", created_by=author
        )
        rule = ApprovalRule.objects.create(
            tenant=tenant,
            content_type=ContentType.objects.get_for_model(SampleTenantScopedRecord),
            name="demo-rule",
            approver_role="resp_commercial",
            fallback_approver_role="direction",
            escalate_after=timedelta(hours=24),
        )
        request = approvals.request_approval(record, rule, author)
    return tenant, author, primary, backup, request


def test_primary_approver_sees_pending_request_immediately(setup) -> None:
    _tenant, _author, primary, _backup, request = setup
    assert request in approvals.pending_for_user(primary)


def test_backup_approver_does_not_see_it_before_escalation_delay(setup) -> None:
    _tenant, _author, _primary, backup, request = setup
    assert request not in approvals.pending_for_user(backup)


def test_backup_approver_sees_it_after_escalation_delay(setup) -> None:
    _tenant, _author, _primary, backup, request = setup
    ApprovalRequest.objects.filter(pk=request.pk).update(
        created_at=timezone.now() - timedelta(hours=25)
    )
    assert request in approvals.pending_for_user(backup)


def test_delegate_approval_makes_request_visible_to_delegate(setup) -> None:
    _tenant, author, primary, _backup, request = setup
    delegate = User.objects.create_user(email="delegate@example.com", password="Str0ngPassw0rd!23")
    approvals.delegate_approval(
        delegator=author,
        delegate=delegate,
        valid_from=timezone.now() - timedelta(hours=1),
        valid_to=timezone.now() + timedelta(hours=1),
    )
    assert request in approvals.pending_for_user(delegate)
