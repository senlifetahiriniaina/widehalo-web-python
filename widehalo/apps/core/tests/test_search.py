from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, Permission

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.search import global_search, index_object
from apps.core.services.search_registry import register_search_source
from apps.core.tests.models import SampleTenantScopedRecord
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@register_search_source(SampleTenantScopedRecord)
def _extract_sample_record(instance: SampleTenantScopedRecord) -> dict:
    return {
        "reference": instance.label,
        "text": instance.label,
        "url": f"/records/{instance.pk}",
    }


@pytest.fixture
def searchable_records():
    tenant = Tenant.objects.create(code="SEARCH-T", name="Search Tenant")
    user = User.objects.create_user(email="searcher@example.com", password="Str0ngPassw0rd!23")
    permission = Permission.objects.get(
        codename="view_sampletenantscopedrecord", content_type__app_label="core"
    )
    group = Group.objects.create(name="search-viewers")
    group.permissions.add(permission)
    user.groups.add(group)

    with use_tenant(tenant.id):
        record_a = SampleTenantScopedRecord.objects.create(tenant=tenant, label="DEV-2026-0142")
        record_b = SampleTenantScopedRecord.objects.create(
            tenant=tenant, label="Bon de commande général"
        )
        index_object(record_a, tenant_id=str(tenant.id))
        index_object(record_b, tenant_id=str(tenant.id))

    return tenant, user, record_a, record_b


def test_exact_reference_match_ranks_first(searchable_records) -> None:
    tenant, user, record_a, _record_b = searchable_records
    results = global_search("DEV-2026-0142", user=user, tenant_id=str(tenant.id))
    assert results
    assert results[0].reference == "DEV-2026-0142"


def test_search_respects_tenant_isolation(searchable_records) -> None:
    _tenant, user, _record_a, _record_b = searchable_records
    other_tenant = Tenant.objects.create(code="SEARCH-T2", name="Other Tenant")
    results = global_search("DEV-2026-0142", user=user, tenant_id=str(other_tenant.id))
    assert results == []


def test_search_hides_results_without_view_permission(searchable_records) -> None:
    tenant, _user, _record_a, _record_b = searchable_records
    unauthorized_user = User.objects.create_user(
        email="noaccess@example.com", password="Str0ngPassw0rd!23"
    )
    results = global_search("DEV-2026-0142", user=unauthorized_user, tenant_id=str(tenant.id))
    assert results == []


def test_full_text_search_finds_by_word() -> None:
    tenant = Tenant.objects.create(code="SEARCH-T3", name="Search Tenant 3")
    user = User.objects.create_user(email="searcher2@example.com", password="Str0ngPassw0rd!23")
    permission = Permission.objects.get(
        codename="view_sampletenantscopedrecord", content_type__app_label="core"
    )
    group = Group.objects.create(name="search-viewers-2")
    group.permissions.add(permission)
    user.groups.add(group)

    with use_tenant(tenant.id):
        record = SampleTenantScopedRecord.objects.create(
            tenant=tenant, label="Facture fournisseur textile"
        )
        index_object(record, tenant_id=str(tenant.id))

    results = global_search("fournisseur", user=user, tenant_id=str(tenant.id))
    assert any("fournisseur" in r.text.lower() for r in results)
