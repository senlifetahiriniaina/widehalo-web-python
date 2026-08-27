"""T10 : la commande `seed_catalog` cree un jeu de demonstration coherent
et est idempotente (rejouee deux fois, ne regenere pas de variantes en
double)."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.catalog.models import (
    CatalogCertification,
    Packaging,
    PriceListItem,
    ProductTemplate,
    ProductVariant,
    TextileSpec,
    UnitConversion,
)
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def test_seed_catalog_creates_coherent_demo_dataset() -> None:
    call_command("seed_catalog", tenant_code="TEST-SEED-CAT")
    tenant = Tenant.objects.get(code="TEST-SEED-CAT")

    with use_tenant(tenant.id):
        assert UnitConversion.objects.filter(tenant=tenant).count() == 2

        templates = ProductTemplate.objects.filter(tenant=tenant)
        assert templates.count() == 2

        variants = ProductVariant.objects.filter(tenant=tenant, template__in=templates)
        assert variants.count() == 3 + 3 * 3  # 3 tissus + 3 couleurs x 3 tailles

        assert TextileSpec.objects.filter(tenant=tenant).count() == 1
        assert PriceListItem.objects.filter(tenant=tenant).count() == 3
        assert Packaging.objects.filter(tenant=tenant).count() == 1
        assert CatalogCertification.objects.filter(tenant=tenant).count() == 1

        demo_user = User.objects.get(email="admin.demo@widehalo.local")
        assert demo_user.groups.filter(name="admin").exists()


def test_seed_catalog_is_idempotent() -> None:
    call_command("seed_catalog", tenant_code="TEST-SEED-CAT-IDEMP")
    call_command("seed_catalog", tenant_code="TEST-SEED-CAT-IDEMP")

    tenant = Tenant.objects.get(code="TEST-SEED-CAT-IDEMP")
    with use_tenant(tenant.id):
        templates = ProductTemplate.objects.filter(tenant=tenant)
        assert templates.count() == 2
        variants = ProductVariant.objects.filter(tenant=tenant, template__in=templates)
        assert variants.count() == 3 + 3 * 3
