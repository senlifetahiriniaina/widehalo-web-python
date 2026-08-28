from __future__ import annotations

import pytest

from apps.catalog.models import ProductVariant
from apps.catalog.services.defaults import ensure_default_variant
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(code="CAT-QUALIF-T", name="Catalog Qualif Tenant")


def test_ensure_default_variant_creates_a_placeholder(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        variant = ensure_default_variant(tenant)
        assert variant.is_placeholder is True
        assert variant.template.category is not None
        assert variant.template.category.name == "Non classé"


def test_ensure_default_variant_is_idempotent(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        first = ensure_default_variant(tenant)
        second = ensure_default_variant(tenant)
        count = ProductVariant.objects.filter(tenant=tenant, is_placeholder=True).count()
        assert first.id == second.id
        assert count == 1
