from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.mrp.services.bom import activate_bom, create_bom
from apps.patronage.models import PatPattern, PatSizeChart
from apps.patronage.services.eco import (
    EcoApprovalRequiredError,
    impacted_boms,
    validate_pattern_version,
)
from apps.patronage.services.patterns import (
    add_pattern_piece,
    create_pattern,
    generate_piece_geometry,
    new_pattern_version,
    validate_pattern,
)
from apps.patronage.services.variation import variation_points

pytestmark = pytest.mark.django_db


@pytest.fixture
def eco_setup():
    tenant = Tenant.objects.create(code="PAT-ECO", name="Patronage Eco Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="prod@example.com", password="Str0ngPassw0rd!23")
        product_id = uuid.uuid4()
        material_id = uuid.uuid4()
        size_chart = PatSizeChart.objects.create(
            tenant=tenant,
            code="TSHIRT-U",
            name="T-shirt unisexe",
            garment_type=PatSizeChart.GARMENT_TSHIRT,
            sizes=["S", "M"],
            base_size="S",
        )
        pattern = create_pattern(
            tenant=tenant,
            code="PAT-1",
            name="T-shirt",
            size_chart=size_chart,
            product_template_id=product_id,
        )
        piece = add_pattern_piece(
            pattern, code="devant", name="Devant", material_variant_id=material_id
        )
        generate_piece_geometry(
            piece,
            size="S",
            graded_measurements={"tour_poitrine": Decimal(90), "longueur": Decimal(65)},
        )
        validate_pattern(pattern)
        return tenant, user, pattern, product_id


def test_variation_points_expose_sizes_and_materials(eco_setup) -> None:
    tenant, _user, pattern, _product_id = eco_setup
    with use_tenant(tenant.id):
        points = variation_points(pattern)
        assert points["sizes"] == ["S", "M"]
        assert len(points["material_variant_ids"]) == 1


def test_no_impacted_boms_needs_no_approval(eco_setup) -> None:
    tenant, user, pattern, _product_id = eco_setup
    with use_tenant(tenant.id):
        v2 = new_pattern_version(pattern)
        validated = validate_pattern_version(v2, requested_by=user)
        assert validated.state == PatPattern.STATE_VALIDATED


def test_impacted_bom_requires_approval(eco_setup) -> None:
    tenant, user, pattern, product_id = eco_setup
    with use_tenant(tenant.id):
        bom = create_bom(tenant=tenant, code="BOM-TS", product_template_id=product_id)
        activate_bom(bom)

        assert impacted_boms(pattern)

        v2 = new_pattern_version(pattern)
        with pytest.raises(EcoApprovalRequiredError):
            validate_pattern_version(v2, requested_by=user)
