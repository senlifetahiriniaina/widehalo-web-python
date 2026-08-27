"""Tests de contraintes structurelles et d'interdependance (T2, CDC §8,
couches 4-5) pour le module `core` — `CHECK`/exclusion, `UNIQUE`, et
comportement `on_delete` des FK. La RLS (isolation tenant) est hors
perimetre ici : voir `test_tenant_isolation.py`.

Deux contraintes de ce module sont deja couvertes ailleurs et ne sont pas
dupliquees :
- `RegulatoryParameter` (exclusion Postgres anti-chevauchement) :
  `test_regulatory_parameter.py::test_overlapping_validity_ranges_are_rejected`.
- Immuabilite de `core_audit_log` (trigger Postgres) : `test_audit_immutability.py`.
"""

from __future__ import annotations

import datetime
import uuid

import pytest
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError

from apps.core.models.document import Document
from apps.core.models.notification import Notification
from apps.core.models.rbac import RoleProfile
from apps.core.models.search import SearchDocument
from apps.core.models.sequence import Sequence
from apps.core.models.tenant import Tenant
from apps.core.models.ui import SavedTableView
from apps.core.models.user import User, UserTenantMembership
from apps.core.models.workflow import ApprovalRequest, ApprovalRule
from apps.core.tests.factories import (
    ApprovalRuleFactory,
    IdempotencyKeyFactory,
    UserFactory,
)
from apps.core.tests.models import SampleTenantScopedRecord
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


# --- UNIQUE / UniqueConstraint --------------------------------------------


def test_sequence_is_unique_per_tenant_code_and_fiscal_year() -> None:
    tenant = Tenant.objects.create(code="SEQ-UNIQ", name="Sequence Tenant")
    with use_tenant(tenant.id):
        Sequence.objects.create(tenant=tenant, code="INV", fiscal_year=2026)
        with pytest.raises(IntegrityError), transaction.atomic():
            Sequence.objects.create(tenant=tenant, code="INV", fiscal_year=2026)


def test_user_tenant_membership_is_unique_per_user_and_tenant() -> None:
    tenant = Tenant.objects.create(code="UTM-UNIQ", name="Membership Tenant")
    user = User.objects.create_user(email="member@example.com", password="Str0ngPassw0rd!23")
    UserTenantMembership.objects.create(user=user, tenant=tenant)
    with pytest.raises(IntegrityError), transaction.atomic():
        UserTenantMembership.objects.create(user=user, tenant=tenant)


def test_saved_table_view_is_unique_per_owner_table_key_and_name() -> None:
    tenant = Tenant.objects.create(code="STV-UNIQ", name="SavedView Tenant")
    owner = User.objects.create_user(email="owner@example.com", password="Str0ngPassw0rd!23")
    with use_tenant(tenant.id):
        SavedTableView.objects.create(
            tenant=tenant, table_key="partners.list", name="Vue A", owner=owner
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            SavedTableView.objects.create(
                tenant=tenant, table_key="partners.list", name="Vue A", owner=owner
            )


def test_search_document_is_unique_per_content_type_and_object_id() -> None:
    content_type = ContentType.objects.get_for_model(Tenant)
    object_id = str(uuid.uuid4())
    SearchDocument.objects.create(
        tenant_id=uuid.uuid4(), content_type=content_type, object_id=object_id, text="Un"
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        SearchDocument.objects.create(
            tenant_id=uuid.uuid4(), content_type=content_type, object_id=object_id, text="Deux"
        )


def test_idempotency_key_is_unique_per_tenant_user_and_key() -> None:
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    IdempotencyKeyFactory(tenant_id=tenant_id, user_id=user_id, key="op-1")
    with pytest.raises(IntegrityError), transaction.atomic():
        IdempotencyKeyFactory(tenant_id=tenant_id, user_id=user_id, key="op-1")


def test_document_sha256_is_unique_per_tenant() -> None:
    tenant = Tenant.objects.create(code="DOC-UNIQ", name="Document Tenant")
    with use_tenant(tenant.id):
        Document.objects.create(
            tenant=tenant, original_name="a.txt", sha256="a" * 64, file="documents/a.txt"
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            Document.objects.create(
                tenant=tenant, original_name="b.txt", sha256="a" * 64, file="documents/b.txt"
            )


def test_role_profile_code_is_globally_unique() -> None:
    RoleProfile.objects.create(group=Group.objects.create(name="role-a"), code="MANAGER")
    with pytest.raises(IntegrityError), transaction.atomic():
        RoleProfile.objects.create(group=Group.objects.create(name="role-b"), code="MANAGER")


def test_tenant_code_is_globally_unique() -> None:
    Tenant.objects.create(code="DUP-CODE", name="First")
    with pytest.raises(IntegrityError), transaction.atomic():
        Tenant.objects.create(code="DUP-CODE", name="Second")


def test_user_email_is_globally_unique() -> None:
    User.objects.create_user(email="unique@example.com", password="Str0ngPassw0rd!23")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user(email="unique@example.com", password="Str0ngPassw0rd!23")


# --- on_delete: PROTECT -----------------------------------------------------


def test_deleting_a_tenant_with_dependent_rows_is_protected() -> None:
    """`BaseModel.tenant` est `on_delete=PROTECT` : toute entite metier
    heritant de BaseModel bloque la suppression physique de son tenant."""
    tenant = Tenant.objects.create(code="PROTECT-T", name="Protect Tenant")
    with use_tenant(tenant.id):
        SampleTenantScopedRecord.objects.create(tenant=tenant, label="x")

    with pytest.raises(ProtectedError):
        tenant.delete()


# --- on_delete: CASCADE -----------------------------------------------------


def test_deleting_a_user_cascades_their_notifications() -> None:
    user = UserFactory()
    Notification.objects.create(
        tenant_id=uuid.uuid4(), user=user, notification_type="info", payload={}
    )
    user_id = user.id
    user.delete()
    assert not Notification.objects.filter(user_id=user_id).exists()


def test_deleting_a_group_cascades_its_role_profile() -> None:
    group = Group.objects.create(name="role-cascade")
    profile = RoleProfile.objects.create(group=group, code="ROLE-CASCADE")
    group.delete()
    assert not RoleProfile.objects.filter(pk=profile.pk).exists()


def test_deleting_an_approval_rule_cascades_its_requests() -> None:
    rule = ApprovalRuleFactory()
    request = ApprovalRequest.objects.create(
        rule=rule,
        content_type=ContentType.objects.get_for_model(Tenant),
        object_id=str(uuid.uuid4()),
        requested_by=UserFactory(),
    )
    rule_id = rule.id
    request_id = request.id
    ApprovalRule.objects.filter(pk=rule_id).delete()
    assert not ApprovalRequest.objects.filter(pk=request_id).exists()


# --- on_delete: SET_NULL -----------------------------------------------------
#
# `AuditLog.actor` is declared `on_delete=SET_NULL`, but this is NOT
# exercised here: the immutability trigger from migration
# `0010_audit_log_immutable` (BEFORE UPDATE OR DELETE FOR EACH ROW, no
# exception for the FK-nullification UPDATE Django issues on cascade)
# rejects that very UPDATE, so deleting a `User` who has ever been an
# `AuditLog.actor` currently raises `ProgrammingError` instead of nulling
# the FK. This is a genuine schema-level conflict between the two
# mechanisms, reported to the caller rather than fixed here (out of scope
# for a test-only task) — NOT something a test should assert as correct
# behavior.


def test_deleting_a_tenant_sandbox_source_sets_it_to_null_on_sandboxes() -> None:
    source = Tenant.objects.create(code="SANDBOX-SRC", name="Source Tenant")
    sandbox = Tenant.objects.create(
        code="SANDBOX-CHILD",
        name="Sandbox Tenant",
        is_sandbox=True,
        sandbox_source=source,
        sandbox_expires_at=datetime.datetime.now(tz=datetime.UTC) + datetime.timedelta(days=1),
    )
    source.delete()
    sandbox.refresh_from_db()
    assert sandbox.sandbox_source_id is None


def test_deleting_the_decider_sets_approval_request_decided_by_to_null() -> None:
    rule = ApprovalRuleFactory()
    decider = UserFactory()
    request = ApprovalRequest.objects.create(
        rule=rule,
        content_type=ContentType.objects.get_for_model(Tenant),
        object_id=str(uuid.uuid4()),
        requested_by=UserFactory(),
        decided_by=decider,
    )
    decider.delete()
    request.refresh_from_db()
    assert request.decided_by_id is None
