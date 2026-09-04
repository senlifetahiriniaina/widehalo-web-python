"""Bloc C, C5 (PRD-4) : `catalog.services.public.get_variant_sector_code`
— nouvelle surface cross-app consommée par `mrp` (nudge écran nomenclature
agroalimentaire), même style que `test_certifications.py`."""

from __future__ import annotations

import pytest

from apps.catalog.models import CatalogSectorSpec
from apps.catalog.services.public import get_variant_sector_code
from apps.catalog.tests.factories import CatalogSectorSpecFactory, ProductVariantFactory
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def test_get_variant_sector_code_returns_sector_when_spec_exists() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        variant = ProductVariantFactory(tenant=tenant)
        CatalogSectorSpecFactory(
            tenant=tenant, variant=variant, sector_code=CatalogSectorSpec.SECTOR_AGROALIMENTAIRE,
            attributes={},
        )
        assert get_variant_sector_code(variant.id) == "agroalimentaire"


def test_get_variant_sector_code_is_none_without_spec() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        variant = ProductVariantFactory(tenant=tenant)
        assert get_variant_sector_code(variant.id) is None
