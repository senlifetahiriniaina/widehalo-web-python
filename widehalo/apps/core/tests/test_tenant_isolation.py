"""Test critique : preuve qu'un tenant ne peut JAMAIS voir les donnees d'un
autre tenant, a la fois via l'ORM (TenantManager) et via SQL brut avec
Row-Level Security PostgreSQL (pas seulement un filtrage applicatif
contournable)."""

from __future__ import annotations

import pytest
from django.db import connection

from apps.core.context import clear_current_tenant
from apps.core.models.tenant import Tenant
from apps.core.tests.models import SampleTenantScopedRecord
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def two_tenants_with_records():
    tenant_a = Tenant.objects.create(code="TEST-A", name="Tenant A")
    tenant_b = Tenant.objects.create(code="TEST-B", name="Tenant B")
    with use_tenant(tenant_a.id):
        record_a = SampleTenantScopedRecord.objects.create(tenant=tenant_a, label="secret-a")
    with use_tenant(tenant_b.id):
        record_b = SampleTenantScopedRecord.objects.create(tenant=tenant_b, label="secret-b")
    clear_current_tenant()
    yield tenant_a, tenant_b, record_a, record_b
    clear_current_tenant()


def test_orm_manager_only_returns_current_tenant_records(two_tenants_with_records):
    tenant_a, tenant_b, record_a, record_b = two_tenants_with_records

    with use_tenant(tenant_a.id):
        visible = list(SampleTenantScopedRecord.objects.all())
        assert visible == [record_a]

    with use_tenant(tenant_b.id):
        visible = list(SampleTenantScopedRecord.objects.all())
        assert visible == [record_b]


def test_orm_manager_returns_nothing_without_tenant_context(two_tenants_with_records):
    clear_current_tenant()
    assert list(SampleTenantScopedRecord.objects.all()) == []


def test_raw_sql_cannot_bypass_rls(two_tenants_with_records):
    """Preuve que l'isolation n'est pas qu'applicative : meme une requete
    SQL brute contournant totalement le TenantManager de l'ORM ne peut pas
    lire les lignes d'un autre tenant, tant que `SET LOCAL app.tenant_id`
    n'a pas ete positionne sur ce tenant."""
    tenant_a, tenant_b, record_a, record_b = two_tenants_with_records

    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL app.tenant_id = %s", [str(tenant_a.id)])
        cursor.execute("SELECT id FROM core_test_sample_record WHERE id = %s", [str(record_b.id)])
        assert cursor.fetchone() is None, "Tenant A a pu lire une ligne du Tenant B via SQL brut"

        cursor.execute("SELECT id FROM core_test_sample_record WHERE id = %s", [str(record_a.id)])
        assert cursor.fetchone() is not None, "Tenant A ne peut meme pas lire sa propre ligne"


def test_raw_sql_without_tenant_setting_sees_nothing(two_tenants_with_records):
    """Deny-by-default au niveau SQL : sans `app.tenant_id` positionne,
    aucune ligne n'est visible, meme via SQL brut."""
    with connection.cursor() as cursor:
        cursor.execute("RESET app.tenant_id")
        cursor.execute("SELECT count(*) FROM core_test_sample_record")
        count = cursor.fetchone()[0]
        assert count == 0


def test_cross_tenant_insert_is_rejected_by_rls(two_tenants_with_records):
    """Meme le proprietaire de la table (FORCE ROW LEVEL SECURITY) ne peut
    pas inserer une ligne pour un tenant different de celui positionne en
    session — protection y compris contre un bug applicatif qui melangerait
    les tenants."""
    tenant_a, tenant_b, _record_a, _record_b = two_tenants_with_records

    with use_tenant(tenant_a.id), pytest.raises(Exception, match="row-level security"):
        SampleTenantScopedRecord.objects.create(tenant=tenant_b, label="devrait-echouer")
