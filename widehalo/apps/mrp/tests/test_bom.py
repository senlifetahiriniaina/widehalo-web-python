from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.mrp.models import MrpBom
from apps.mrp.services.bom import (
    activate_bom,
    add_bom_line,
    add_by_product,
    create_bom,
    explode,
    new_version,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def bom_setup():
    tenant = Tenant.objects.create(code="MRP-BOM", name="MRP BOM Tenant")
    with use_tenant(tenant.id):
        return tenant


def test_self_reference_is_rejected_as_cycle(bom_setup) -> None:
    tenant = bom_setup
    with use_tenant(tenant.id):
        product_id = uuid.uuid4()
        bom = create_bom(tenant=tenant, code="BOM-1", product_template_id=product_id)
        with pytest.raises(ValidationError):
            add_bom_line(bom, component_template_id=product_id, qty=Decimal(1))


def test_transitive_cycle_through_active_sub_bom_is_rejected(bom_setup) -> None:
    tenant = bom_setup
    with use_tenant(tenant.id):
        product_a = uuid.uuid4()
        product_b = uuid.uuid4()

        bom_b = create_bom(tenant=tenant, code="BOM-B", product_template_id=product_b)
        add_bom_line(bom_b, component_template_id=product_a, qty=Decimal(1))
        activate_bom(bom_b)

        bom_a = create_bom(tenant=tenant, code="BOM-A", product_template_id=product_a)
        with pytest.raises(ValidationError):
            add_bom_line(bom_a, component_template_id=product_b, qty=Decimal(1))


def test_active_bom_cannot_be_modified(bom_setup) -> None:
    tenant = bom_setup
    with use_tenant(tenant.id):
        product_id = uuid.uuid4()
        component_id = uuid.uuid4()
        bom = create_bom(tenant=tenant, code="BOM-1", product_template_id=product_id)
        activate_bom(bom)
        with pytest.raises(ValidationError):
            add_bom_line(bom, component_template_id=component_id, qty=Decimal(1))


def test_new_version_copies_lines_and_keeps_original_intact(bom_setup) -> None:
    tenant = bom_setup
    with use_tenant(tenant.id):
        product_id = uuid.uuid4()
        component_id = uuid.uuid4()
        bom = create_bom(tenant=tenant, code="BOM-1", product_template_id=product_id)
        add_bom_line(bom, component_template_id=component_id, qty=Decimal(2))
        activate_bom(bom)

        v2 = new_version(bom)
        assert v2.version == 2
        assert v2.state == MrpBom.STATE_DRAFT
        assert v2.lines.count() == 1

        bom.refresh_from_db()
        assert bom.state == MrpBom.STATE_ACTIVE
        assert bom.lines.count() == 1


def test_activating_new_version_obsoletes_previous(bom_setup) -> None:
    tenant = bom_setup
    with use_tenant(tenant.id):
        product_id = uuid.uuid4()
        bom = create_bom(tenant=tenant, code="BOM-1", product_template_id=product_id)
        activate_bom(bom)
        v2 = new_version(bom)
        activate_bom(v2)

        bom.refresh_from_db()
        assert bom.state == MrpBom.STATE_OBSOLETE
        v2.refresh_from_db()
        assert v2.state == MrpBom.STATE_ACTIVE


def test_waste_pct_majorates_planned_quantity(bom_setup) -> None:
    tenant = bom_setup
    with use_tenant(tenant.id):
        product_id = uuid.uuid4()
        component_id = uuid.uuid4()
        bom = create_bom(tenant=tenant, code="BOM-1", product_template_id=product_id)
        add_bom_line(bom, component_template_id=component_id, qty=Decimal(2), waste_pct=Decimal(10))
        activate_bom(bom)

        rows = explode(bom, Decimal(1))
        assert rows[0]["qty"] == Decimal("2.2")


def test_qty_by_size_applied_at_each_level(bom_setup) -> None:
    tenant = bom_setup
    with use_tenant(tenant.id):
        product_top = uuid.uuid4()
        product_mid = uuid.uuid4()
        product_leaf = uuid.uuid4()

        bom_mid = create_bom(tenant=tenant, code="BOM-MID", product_template_id=product_mid)
        add_bom_line(
            bom_mid,
            component_template_id=product_leaf,
            qty=Decimal(1),
            qty_by_size={"L": "1.36"},
        )
        activate_bom(bom_mid)

        bom_top = create_bom(tenant=tenant, code="BOM-TOP", product_template_id=product_top)
        add_bom_line(
            bom_top,
            component_template_id=product_mid,
            qty=Decimal(1),
            qty_by_size={"L": "2"},
        )
        activate_bom(bom_top)

        rows = explode(bom_top, Decimal(100), size="L")
        mid_row = next(r for r in rows if r["component_template_id"] == product_mid)
        leaf_row = next(r for r in rows if r["component_template_id"] == product_leaf)

        assert mid_row["qty"] == Decimal("200")
        assert leaf_row["qty"] == Decimal("272.00")


def test_conditional_component_skipped_without_matching_attribute(bom_setup) -> None:
    tenant = bom_setup
    with use_tenant(tenant.id):
        product_id = uuid.uuid4()
        lining_id = uuid.uuid4()
        bom = create_bom(tenant=tenant, code="BOM-1", product_template_id=product_id)
        add_bom_line(
            bom,
            component_template_id=lining_id,
            qty=Decimal(1),
            apply_on_attribute_values=["color:black"],
        )
        activate_bom(bom)

        rows_without_match = explode(bom, Decimal(1), attribute_values=["color:white"])
        rows_with_match = explode(bom, Decimal(1), attribute_values=["color:black"])

        assert rows_without_match == []
        assert len(rows_with_match) == 1


def test_add_by_product_requires_process_type(bom_setup) -> None:
    tenant = bom_setup
    with use_tenant(tenant.id):
        product_id = uuid.uuid4()
        bom = create_bom(tenant=tenant, code="BOM-MFG", product_template_id=product_id)
        with pytest.raises(ValidationError):
            add_by_product(bom, component_template_id=uuid.uuid4(), expected_qty_pct=Decimal("10"))


def test_add_by_product_refuses_on_active_bom(bom_setup) -> None:
    tenant = bom_setup
    with use_tenant(tenant.id):
        product_id = uuid.uuid4()
        bom = create_bom(
            tenant=tenant, code="BOM-PROC", product_template_id=product_id, type=MrpBom.TYPE_PROCESS
        )
        activate_bom(bom)
        with pytest.raises(ValidationError):
            add_by_product(bom, component_template_id=uuid.uuid4(), expected_qty_pct=Decimal("10"))


def test_add_by_product_declares_yield_and_coproduct_data(bom_setup) -> None:
    """Bloc C, C5 (PRD-7) : nomenclature de process avec rendement +
    sous-produit déclarés — données purement déclaratives, consommées
    par la réconciliation matière de C3."""
    tenant = bom_setup
    with use_tenant(tenant.id):
        product_id = uuid.uuid4()
        by_product_id = uuid.uuid4()
        bom = create_bom(
            tenant=tenant, code="BOM-PROC", product_template_id=product_id, type=MrpBom.TYPE_PROCESS
        )
        bom.expected_yield_pct = Decimal("85")
        bom.save(update_fields=["expected_yield_pct"])

        add_by_product(
            bom,
            component_template_id=by_product_id,
            expected_qty_pct=Decimal("12.50"),
            label="Sous-produit A",
            is_coproduct=True,
        )
        bom.refresh_from_db()
        assert bom.expected_yield_pct == Decimal("85")
        assert bom.by_products == [
            {
                "component_template_id": str(by_product_id),
                "label": "Sous-produit A",
                "expected_qty_pct": "12.50",
                "is_coproduct": True,
            }
        ]


def test_new_version_copies_yield_and_by_products(bom_setup) -> None:
    tenant = bom_setup
    with use_tenant(tenant.id):
        product_id = uuid.uuid4()
        by_product_id = uuid.uuid4()
        bom = create_bom(
            tenant=tenant, code="BOM-PROC", product_template_id=product_id, type=MrpBom.TYPE_PROCESS
        )
        bom.expected_yield_pct = Decimal("90")
        bom.save(update_fields=["expected_yield_pct"])
        add_by_product(bom, component_template_id=by_product_id, expected_qty_pct=Decimal("5"))
        activate_bom(bom)

        v2 = new_version(bom)
        assert v2.expected_yield_pct == Decimal("90")
        assert v2.by_products == bom.by_products
        # Copie independante : muter la v2 n'affecte pas la v1 archivee.
        add_by_product(v2, component_template_id=uuid.uuid4(), expected_qty_pct=Decimal("1"))
        bom.refresh_from_db()
        assert len(bom.by_products) == 1
        assert len(v2.by_products) == 2


def test_explode_ignores_by_products_declaration(bom_setup) -> None:
    """Preuve du perimetre scope C5 : les sous-produits/coproduits sont
    purement declaratifs, `explode()` (le seul point qui materialise les
    composants d'un ordre reel) ne les voit jamais."""
    tenant = bom_setup
    with use_tenant(tenant.id):
        product_id = uuid.uuid4()
        component_id = uuid.uuid4()
        bom = create_bom(
            tenant=tenant, code="BOM-PROC", product_template_id=product_id, type=MrpBom.TYPE_PROCESS
        )
        add_bom_line(bom, component_template_id=component_id, qty=Decimal(2))
        add_by_product(bom, component_template_id=uuid.uuid4(), expected_qty_pct=Decimal("10"))
        activate_bom(bom)

        rows = explode(bom, Decimal(5))
        assert len(rows) == 1
        assert rows[0]["component_template_id"] == component_id
