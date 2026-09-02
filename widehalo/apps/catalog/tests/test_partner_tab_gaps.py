"""Tests du gap PT5 (chantier "fiche partenaire a onglets par role") sur
le contrat public de `catalog` : `list_supplier_products`."""

from __future__ import annotations

import uuid

import pytest

from apps.catalog.services.public import list_supplier_products
from apps.catalog.tests.factories import ProductSupplierInfoFactory, ProductVariantFactory
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def test_list_supplier_products_returns_rows_for_that_partner() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        partner_id = uuid.uuid4()
        variant = ProductVariantFactory(tenant=tenant)
        info = ProductSupplierInfoFactory(
            tenant=tenant, variant=variant, partner_id=partner_id, supplier_reference="SUP-1"
        )
        ProductSupplierInfoFactory(tenant=tenant)  # other partner, must not appear

        rows = list_supplier_products(partner_id)

        assert len(rows) == 1
        assert rows[0]["variant_id"] == variant.id
        assert rows[0]["variant_reference"] == variant.reference
        assert rows[0]["product_name"] == variant.template.name
        assert rows[0]["supplier_reference"] == "SUP-1"
        assert rows[0]["price_mga"] == info.price_mga
        assert rows[0]["lead_time_days"] == info.lead_time_days


def test_list_supplier_products_returns_empty_list_for_unknown_partner() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        assert list_supplier_products(uuid.uuid4()) == []


def test_list_supplier_products_respects_limit() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        partner_id = uuid.uuid4()
        for _ in range(3):
            ProductSupplierInfoFactory(tenant=tenant, partner_id=partner_id)

        rows = list_supplier_products(partner_id, limit=2)

        assert len(rows) == 2
