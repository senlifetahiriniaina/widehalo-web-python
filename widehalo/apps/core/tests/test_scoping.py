from __future__ import annotations

import pytest

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.scoping import apply_scope
from apps.core.tests.models import SampleTenantScopedRecord
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def test_own_scope_only_returns_records_created_by_user() -> None:
    tenant = Tenant.objects.create(code="SCOPE-T", name="Scope Tenant")
    alice = User.objects.create_user(email="alice@example.com", password="Str0ngPassw0rd!23")
    bob = User.objects.create_user(email="bob@example.com", password="Str0ngPassw0rd!23")

    with use_tenant(tenant.id):
        record_alice = SampleTenantScopedRecord.objects.create(
            tenant=tenant, label="alice-record", created_by=alice
        )
        SampleTenantScopedRecord.objects.create(tenant=tenant, label="bob-record", created_by=bob)

        scoped = apply_scope(SampleTenantScopedRecord.objects.all(), alice, "own")
        assert list(scoped) == [record_alice]


def test_global_scope_returns_everything_visible_to_tenant() -> None:
    tenant = Tenant.objects.create(code="SCOPE-T2", name="Scope Tenant 2")
    alice = User.objects.create_user(email="alice2@example.com", password="Str0ngPassw0rd!23")

    with use_tenant(tenant.id):
        SampleTenantScopedRecord.objects.create(tenant=tenant, label="r1", created_by=alice)
        SampleTenantScopedRecord.objects.create(tenant=tenant, label="r2", created_by=alice)

        scoped = apply_scope(SampleTenantScopedRecord.objects.all(), alice, "global")
        assert scoped.count() == 2


def test_field_masking_hides_sensitive_field_for_unauthorized_role() -> None:
    from apps.core.services.permissions import SENSITIVE_FIELDS, filter_fields_for_role

    SENSITIVE_FIELDS["tests.DemoModel"] = {"marge": {"direction", "admin"}}
    try:
        data = {"reference": "DEV-001", "marge": 1234}

        assert filter_fields_for_role("tests.DemoModel", {"collaborateur"}, data) == {
            "reference": "DEV-001"
        }
        assert filter_fields_for_role("tests.DemoModel", {"direction"}, data) == data
    finally:
        del SENSITIVE_FIELDS["tests.DemoModel"]
