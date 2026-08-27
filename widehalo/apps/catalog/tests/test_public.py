"""Tests du contrat public de `catalog` (`apps/catalog/services/public.py`)
— seule surface que les autres apps metier ont le droit d'importer. Couvre
ici le gap ajoute pour RG-SAL-3 (S3 du sous-sequencement `sales`, cf.
plan) : `get_variant_template_id`."""

from __future__ import annotations

import uuid

import pytest

from apps.catalog.models import ProductSupplierInfo, ProductTemplate, ProductVariant, UnitOfMeasure
from apps.catalog.services.public import get_supplier_lead_time_days, get_variant_template_id
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def variant_setup():
    tenant = Tenant.objects.create(code="CAT-PUB", name="Catalog Public Tenant")
    with use_tenant(tenant.id):
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="U", name="Unite", category=UnitOfMeasure.CATEGORY_COUNT
        )
        template = ProductTemplate.objects.create(
            tenant=tenant, name="Polo", base_uom=uom, reference="TPL-PUB-0001"
        )
        variant = ProductVariant.objects.create(
            tenant=tenant, template=template, reference="VAR-PUB-0001"
        )
        return tenant, template, variant


def test_get_variant_template_id_resolves_existing_variant(variant_setup) -> None:
    tenant, template, variant = variant_setup
    with use_tenant(tenant.id):
        assert get_variant_template_id(variant.id) == template.id


def test_get_variant_template_id_returns_none_for_unknown_variant(variant_setup) -> None:
    tenant, _template, _variant = variant_setup
    with use_tenant(tenant.id):
        assert get_variant_template_id(uuid.uuid4()) is None


def test_get_supplier_lead_time_days_returns_minimum_across_suppliers(variant_setup) -> None:
    """RG-SAL-7 (S6 du sous-sequencement `sales`) : le minimum, l'hypothese
    la plus optimiste, sert de delai fournisseur par defaut."""
    tenant, _template, variant = variant_setup
    with use_tenant(tenant.id):
        partner_fast = uuid.uuid4()
        partner_slow = uuid.uuid4()
        ProductSupplierInfo.objects.create(
            tenant=tenant, variant=variant, partner_id=partner_fast, lead_time_days=5
        )
        ProductSupplierInfo.objects.create(
            tenant=tenant, variant=variant, partner_id=partner_slow, lead_time_days=20
        )

        assert get_supplier_lead_time_days(variant.id) == 5
        assert get_supplier_lead_time_days(variant.id, partner_id=partner_slow) == 20


def test_get_supplier_lead_time_days_returns_none_without_supplier_info(variant_setup) -> None:
    tenant, _template, variant = variant_setup
    with use_tenant(tenant.id):
        assert get_supplier_lead_time_days(variant.id) is None


def test_get_supplier_lead_time_days_returns_none_for_unknown_variant(variant_setup) -> None:
    tenant, _template, _variant = variant_setup
    with use_tenant(tenant.id):
        assert get_supplier_lead_time_days(uuid.uuid4()) is None
