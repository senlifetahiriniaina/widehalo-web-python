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

from decimal import Decimal

import pytest
from django.db import IntegrityError, connection, transaction
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
from apps.stocks.models import StkLocation, StkMove
from apps.stocks.tests.factories import StkLocationFactory, StkMoveFactory, StkQuantFactory

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


# --- DB triggers (STK-11, Phase 3 sprint A5) --------------------------------


def test_template_uom_change_is_refused_once_a_variant_has_a_done_move(tenant) -> None:
    """catalog.0013 : `catalog_product_template_uom_immutable_after_movement`.
    Le mouvement doit etre `done` — un simple `draft` (creation en cours,
    pas encore valide) ne verrouille pas encore l'unite."""
    with use_tenant(tenant.id):
        template = ProductTemplateFactory(tenant=tenant)
        variant = ProductVariantFactory(tenant=tenant, template=template)
        StkMoveFactory(tenant=tenant, variant_id=variant.id, state=StkMove.STATE_DONE)
        new_uom = UnitOfMeasureFactory(tenant=tenant)

        template.base_uom = new_uom
        with pytest.raises(Exception, match="immuable"), transaction.atomic():
            template.save(update_fields=["base_uom"])


def test_template_uom_change_is_refused_even_via_raw_sql(tenant) -> None:
    """Meme discipline « ceinture et bretelles » que
    `stocks.tests.test_structural_constraints::test_done_move_is_immutable_even_via_raw_sql` :
    le trigger doit refuser meme un UPDATE SQL direct, pas seulement un
    `.save()` ORM."""
    with use_tenant(tenant.id):
        template = ProductTemplateFactory(tenant=tenant)
        variant = ProductVariantFactory(tenant=tenant, template=template)
        StkMoveFactory(tenant=tenant, variant_id=variant.id, state=StkMove.STATE_DONE)
        new_uom = UnitOfMeasureFactory(tenant=tenant)

        with (
            pytest.raises(Exception, match="immuable"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE catalog_product_template SET base_uom_id = %s WHERE id = %s",
                [str(new_uom.id), str(template.id)],
            )


def test_template_uom_change_is_allowed_before_any_done_move(tenant) -> None:
    with use_tenant(tenant.id):
        template = ProductTemplateFactory(tenant=tenant)
        variant = ProductVariantFactory(tenant=tenant, template=template)
        StkMoveFactory(tenant=tenant, variant_id=variant.id, state=StkMove.STATE_DRAFT)
        new_uom = UnitOfMeasureFactory(tenant=tenant)

        template.base_uom = new_uom
        template.save(update_fields=["base_uom"])  # ne doit pas lever

        template.refresh_from_db()
        assert template.base_uom_id == new_uom.id


def test_variant_lot_tracking_flip_is_refused_when_internal_stock_is_non_zero(tenant) -> None:
    """catalog.0013 : `catalog_product_variant_lot_tracking_flip_guard`.
    « Stock non nul » = emplacements INTERNES uniquement (meme perimetre
    que `stocks.services.quants.on_hand_qty`)."""
    with use_tenant(tenant.id):
        variant = ProductVariantFactory(tenant=tenant, is_lot_tracked=False)
        internal = StkLocationFactory(tenant=tenant, type=StkLocation.TYPE_INTERNE)
        StkQuantFactory(tenant=tenant, variant_id=variant.id, location=internal, qty=Decimal("5"))

        variant.is_lot_tracked = True
        with pytest.raises(Exception, match="stock"), transaction.atomic():
            variant.save(update_fields=["is_lot_tracked"])


def test_variant_lot_tracking_flip_is_allowed_when_internal_stock_is_zero(tenant) -> None:
    with use_tenant(tenant.id):
        variant = ProductVariantFactory(tenant=tenant, is_lot_tracked=False)

        variant.is_lot_tracked = True
        variant.save(update_fields=["is_lot_tracked"])  # ne doit pas lever

        variant.refresh_from_db()
        assert variant.is_lot_tracked is True


def test_variant_lot_tracking_flip_ignores_stock_on_virtual_locations(tenant) -> None:
    """Un quant sur un emplacement VIRTUEL (ex. fournisseur) n'est pas du
    stock physique — meme perimetre d'exclusion que `on_hand_qty`, le
    trigger ne doit donc pas le compter."""
    with use_tenant(tenant.id):
        variant = ProductVariantFactory(tenant=tenant, is_lot_tracked=False)
        supplier = StkLocationFactory(tenant=tenant, type=StkLocation.TYPE_FOURNISSEUR)
        StkQuantFactory(tenant=tenant, variant_id=variant.id, location=supplier, qty=Decimal("-42"))

        variant.is_lot_tracked = True
        variant.save(update_fields=["is_lot_tracked"])  # ne doit pas lever

        variant.refresh_from_db()
        assert variant.is_lot_tracked is True


def test_variant_lot_tracking_unflip_is_always_allowed(tenant) -> None:
    """Le CDC ne contraint que le sens non -> oui — un retour a `False`
    reste libre, meme avec du stock physique present."""
    with use_tenant(tenant.id):
        variant = ProductVariantFactory(tenant=tenant, is_lot_tracked=True)
        internal = StkLocationFactory(tenant=tenant, type=StkLocation.TYPE_INTERNE)
        StkQuantFactory(tenant=tenant, variant_id=variant.id, location=internal, qty=Decimal("5"))

        variant.is_lot_tracked = False
        variant.save(update_fields=["is_lot_tracked"])  # ne doit pas lever

        variant.refresh_from_db()
        assert variant.is_lot_tracked is False
