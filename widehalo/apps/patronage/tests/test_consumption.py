from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.mrp.models import MrpBomLine
from apps.mrp.services.bom import create_bom
from apps.patronage.models import PatSizeChart
from apps.patronage.services.consumption import (
    compute_consumption,
    compute_marker,
    push_to_bom,
    revert_push_to_bom,
)
from apps.patronage.services.patterns import (
    add_pattern_piece,
    create_pattern,
    generate_piece_geometry,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def consumption_setup():
    tenant = Tenant.objects.create(code="PAT-CONS", name="Patronage Consumption Tenant")
    with use_tenant(tenant.id):
        size_chart = PatSizeChart.objects.create(
            tenant=tenant,
            code="TSHIRT-U",
            name="T-shirt unisexe",
            garment_type=PatSizeChart.GARMENT_TSHIRT,
            sizes=["S", "M", "L"],
            base_size="S",
        )
        pattern = create_pattern(
            tenant=tenant, code="PAT-1", name="T-shirt basique", size_chart=size_chart
        )
        material_id = uuid.uuid4()
        piece = add_pattern_piece(
            pattern, code="devant", name="Devant", material_variant_id=material_id
        )
        generate_piece_geometry(
            piece,
            size="M",
            graded_measurements={"tour_poitrine": Decimal(100), "longueur": Decimal(70)},
        )
        return tenant, pattern, piece, material_id


def test_compute_consumption_from_geometry_area(consumption_setup) -> None:
    tenant, pattern, _piece, material_id = consumption_setup
    with use_tenant(tenant.id):
        consumption = compute_consumption(
            pattern, size="M", material_variant_id=material_id, width_cm=Decimal(150)
        )
        # aire = (100/4+2) x 70 = 27 x 70 = 1890 cm2 ; laize 150cm -> 12.6 cm -> 0.126 m
        assert consumption.length_m == Decimal(1890) / Decimal(150) / Decimal(100)


def test_compute_consumption_without_geometry_raises(consumption_setup) -> None:
    tenant, pattern, _piece, _material_id = consumption_setup
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        compute_consumption(
            pattern, size="L", material_variant_id=uuid.uuid4(), width_cm=Decimal(150)
        )


def test_compute_marker_applies_efficiency(consumption_setup) -> None:
    tenant, pattern, _piece, material_id = consumption_setup
    with use_tenant(tenant.id):
        marker = compute_marker(
            pattern,
            material_variant_id=material_id,
            fabric_width_cm=Decimal(150),
            size_ratio={"M": 2},
            efficiency_pct=Decimal(90),
        )
        assert marker.length_m > 0


def test_push_to_bom_sets_qty_by_size_on_matching_line(consumption_setup) -> None:
    tenant, pattern, _piece, material_id = consumption_setup
    with use_tenant(tenant.id):
        compute_consumption(
            pattern, size="M", material_variant_id=material_id, width_cm=Decimal(150)
        )

        bom = create_bom(tenant=tenant, code="BOM-TS", product_template_id=uuid.uuid4())
        line = MrpBomLine.objects.create(
            tenant=tenant,
            bom=bom,
            component_template_id=uuid.uuid4(),
            component_variant_id=material_id,
        )

        applied = push_to_bom(pattern, bom_id=bom.id, material_variant_id=material_id)
        assert applied
        line.refresh_from_db()
        assert "M" in line.qty_by_size


def test_push_to_bom_returns_false_without_matching_line(consumption_setup) -> None:
    tenant, pattern, _piece, material_id = consumption_setup
    with use_tenant(tenant.id):
        compute_consumption(
            pattern, size="M", material_variant_id=material_id, width_cm=Decimal(150)
        )
        bom = create_bom(tenant=tenant, code="BOM-EMPTY", product_template_id=uuid.uuid4())

        applied = push_to_bom(pattern, bom_id=bom.id, material_variant_id=material_id)
        assert not applied


def test_push_to_bom_rejects_active_bom(consumption_setup) -> None:
    from apps.mrp.services.bom import activate_bom

    tenant, pattern, _piece, material_id = consumption_setup
    with use_tenant(tenant.id):
        compute_consumption(
            pattern, size="M", material_variant_id=material_id, width_cm=Decimal(150)
        )
        bom = create_bom(tenant=tenant, code="BOM-ACTIVE", product_template_id=uuid.uuid4())
        MrpBomLine.objects.create(
            tenant=tenant,
            bom=bom,
            component_template_id=uuid.uuid4(),
            component_variant_id=material_id,
        )
        activate_bom(bom)

        with pytest.raises(ValidationError):
            push_to_bom(pattern, bom_id=bom.id, material_variant_id=material_id)


def test_revert_push_to_bom_clears_qty_by_size(consumption_setup) -> None:
    tenant, pattern, _piece, material_id = consumption_setup
    with use_tenant(tenant.id):
        compute_consumption(
            pattern, size="M", material_variant_id=material_id, width_cm=Decimal(150)
        )
        bom = create_bom(tenant=tenant, code="BOM-REV", product_template_id=uuid.uuid4())
        line = MrpBomLine.objects.create(
            tenant=tenant,
            bom=bom,
            component_template_id=uuid.uuid4(),
            component_variant_id=material_id,
        )
        push_to_bom(pattern, bom_id=bom.id, material_variant_id=material_id)
        revert_push_to_bom(pattern, bom_id=bom.id, material_variant_id=material_id)
        line.refresh_from_db()
        assert line.qty_by_size == {}
