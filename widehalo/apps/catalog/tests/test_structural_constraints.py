"""Tests de contraintes structurelles et d'interdependance (T2, CDC §8,
couches 4-5) pour le module `catalog`. La RLS est hors perimetre.

Constraintes reellement absentes en base (pas des trous de tests, un choix
de modelisation actuel), volontairement NON testees ici comme si elles
existaient :
- `ProductVariant` : aucune `UniqueConstraint` empechant deux variantes du
  meme template de porter exactement la meme combinaison de valeurs
  d'attributs (le M2M `attribute_values` ne se prete pas a une contrainte
  SQL simple) — la deduplication, si necessaire, releverait de
  `services/variants.py::generate_variants`.
- `UnitConversion` : pas d'unicite DB sur `(from_unit, to_unit)` — deux
  facteurs de conversion contradictoires pour la meme paire d'unites
  pourraient coexister.
- `AttributeValue` : pas d'unicite DB sur `(attribute, value)`.
Ces trois points sont signales dans le rapport de cette tache comme des
ecarts de schema potentiels, pas corriges ici (hors perimetre : test-only)."""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError

from apps.catalog.models import (
    CatalogCertification,
    Category,
    Packaging,
    PriceListItem,
    ProductSupplierInfo,
    ProductTemplate,
    ProductVariant,
    TextileSpec,
)
from apps.catalog.tests.factories import (
    CatalogCertificationFactory,
    CategoryFactory,
    PackagingFactory,
    PriceListFactory,
    PriceListItemFactory,
    ProductSupplierInfoFactory,
    ProductTemplateFactory,
    ProductVariantFactory,
    TextileSpecFactory,
    UnitOfMeasureFactory,
)
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return Tenant.objects.create(code="CAT-STRUCT", name="Catalog Structural Tenant")


# --- UNIQUE / UniqueConstraint ----------------------------------------------


def test_price_list_item_is_unique_per_price_list_and_variant(tenant) -> None:
    with use_tenant(tenant.id):
        price_list = PriceListFactory(tenant=tenant)
        variant = ProductVariantFactory(tenant=tenant)
        PriceListItem.objects.create(
            tenant=tenant, price_list=price_list, variant=variant, price_mga="1000"
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            PriceListItem.objects.create(
                tenant=tenant, price_list=price_list, variant=variant, price_mga="2000"
            )


# --- on_delete: PROTECT -----------------------------------------------------


def test_deleting_a_tenant_with_catalog_rows_is_protected(tenant) -> None:
    with use_tenant(tenant.id):
        UnitOfMeasureFactory(tenant=tenant)

    with pytest.raises(ProtectedError):
        tenant.delete()


def test_deleting_a_uom_used_by_a_template_is_protected(tenant) -> None:
    with use_tenant(tenant.id):
        template = ProductTemplateFactory(tenant=tenant)
        uom = template.base_uom

    with use_tenant(tenant.id), pytest.raises(ProtectedError):
        uom.delete()


def test_deleting_a_uom_used_by_a_packaging_is_protected(tenant) -> None:
    with use_tenant(tenant.id):
        packaging = PackagingFactory(tenant=tenant)
        uom = packaging.uom

    with use_tenant(tenant.id), pytest.raises(ProtectedError):
        uom.delete()


def test_deleting_a_standard_used_by_a_certification_is_protected(tenant) -> None:
    with use_tenant(tenant.id):
        certification = CatalogCertificationFactory(tenant=tenant)
        standard = certification.standard

    with use_tenant(tenant.id), pytest.raises(ProtectedError):
        standard.delete()


# --- on_delete: CASCADE -----------------------------------------------------


def test_deleting_a_template_cascades_its_variants(tenant) -> None:
    with use_tenant(tenant.id):
        variant = ProductVariantFactory(tenant=tenant)
        template_id = variant.template_id
        variant_id = variant.id

        ProductTemplate.objects.filter(pk=template_id).delete()

        assert not ProductVariant.objects.filter(pk=variant_id).exists()


def test_deleting_a_variant_cascades_its_textile_spec(tenant) -> None:
    with use_tenant(tenant.id):
        spec = TextileSpecFactory(tenant=tenant)
        variant_id = spec.variant_id
        spec_id = spec.id

        ProductVariant.objects.filter(pk=variant_id).delete()

        assert not TextileSpec.objects.filter(pk=spec_id).exists()


def test_deleting_a_variant_cascades_its_supplier_infos(tenant) -> None:
    with use_tenant(tenant.id):
        info = ProductSupplierInfoFactory(tenant=tenant)
        variant_id = info.variant_id
        info_id = info.id

        ProductVariant.objects.filter(pk=variant_id).delete()

        assert not ProductSupplierInfo.objects.filter(pk=info_id).exists()


def test_deleting_a_variant_cascades_its_price_list_items(tenant) -> None:
    with use_tenant(tenant.id):
        item = PriceListItemFactory(tenant=tenant)
        variant_id = item.variant_id
        item_id = item.id

        ProductVariant.objects.filter(pk=variant_id).delete()

        assert not PriceListItem.objects.filter(pk=item_id).exists()


def test_deleting_a_variant_cascades_its_packagings(tenant) -> None:
    with use_tenant(tenant.id):
        packaging = PackagingFactory(tenant=tenant)
        variant_id = packaging.variant_id
        packaging_id = packaging.id

        ProductVariant.objects.filter(pk=variant_id).delete()

        assert not Packaging.objects.filter(pk=packaging_id).exists()


def test_deleting_a_variant_cascades_its_certifications(tenant) -> None:
    with use_tenant(tenant.id):
        certification = CatalogCertificationFactory(tenant=tenant)
        variant_id = certification.variant_id
        certification_id = certification.id

        ProductVariant.objects.filter(pk=variant_id).delete()

        assert not CatalogCertification.objects.filter(pk=certification_id).exists()


# --- on_delete: SET_NULL -----------------------------------------------------


def test_deleting_a_parent_category_sets_children_parent_to_null(tenant) -> None:
    with use_tenant(tenant.id):
        parent = CategoryFactory(tenant=tenant)
        child = CategoryFactory(tenant=tenant, parent=parent)

        parent_id = parent.id
        Category.objects.filter(pk=parent_id).delete()

        child.refresh_from_db()
        assert child.parent_id is None
