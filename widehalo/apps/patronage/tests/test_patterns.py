from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.patronage.models import PatPattern, PatSizeChart
from apps.patronage.services.patterns import (
    add_pattern_piece,
    create_pattern,
    generate_piece_geometry,
    new_pattern_version,
    validate_pattern,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def pattern_setup():
    tenant = Tenant.objects.create(code="PAT-PAT", name="Patronage Pattern Tenant")
    with use_tenant(tenant.id):
        size_chart = PatSizeChart.objects.create(
            tenant=tenant,
            code="CHEMISE-H",
            name="Chemise homme",
            garment_type=PatSizeChart.GARMENT_SHIRT,
            sizes=["S", "M", "L"],
            base_size="S",
        )
        pattern = create_pattern(
            tenant=tenant, code="PAT-1", name="Chemise classique", size_chart=size_chart
        )
        return tenant, pattern


def test_add_piece_to_draft_pattern(pattern_setup) -> None:
    tenant, pattern = pattern_setup
    with use_tenant(tenant.id):
        piece = add_pattern_piece(pattern, code="devant", name="Devant")
        assert piece.pattern_id == pattern.id


def test_cannot_add_piece_to_validated_pattern(pattern_setup) -> None:
    tenant, pattern = pattern_setup
    with use_tenant(tenant.id):
        validate_pattern(pattern)
        with pytest.raises(ValidationError):
            add_pattern_piece(pattern, code="devant", name="Devant")


def test_new_version_copies_pieces_and_keeps_original(pattern_setup) -> None:
    tenant, pattern = pattern_setup
    with use_tenant(tenant.id):
        add_pattern_piece(pattern, code="devant", name="Devant")
        validate_pattern(pattern)

        v2 = new_pattern_version(pattern)
        assert v2.version == 2
        assert v2.state == PatPattern.STATE_DRAFT
        assert v2.pieces.count() == 1

        pattern.refresh_from_db()
        assert pattern.state == PatPattern.STATE_VALIDATED
        assert pattern.pieces.count() == 1


def test_generate_piece_geometry_from_graded_measurements(pattern_setup) -> None:
    tenant, pattern = pattern_setup
    with use_tenant(tenant.id):
        piece = add_pattern_piece(pattern, code="devant", name="Devant")
        geometry = generate_piece_geometry(
            piece,
            size="M",
            graded_measurements={"tour_poitrine": Decimal(96), "longueur": Decimal(70)},
        )
        # 96/4 + 2 (aisance) = 26
        assert geometry.area_cm2 == Decimal(26) * Decimal(70)
        assert geometry.size == "M"


def test_generate_piece_geometry_missing_measurement_raises(pattern_setup) -> None:
    tenant, pattern = pattern_setup
    with use_tenant(tenant.id):
        piece = add_pattern_piece(pattern, code="devant", name="Devant")
        with pytest.raises(ValidationError):
            generate_piece_geometry(piece, size="M", graded_measurements={})


def test_unsupported_garment_type_raises(pattern_setup) -> None:
    tenant, pattern = pattern_setup
    with use_tenant(tenant.id):
        pattern.size_chart.garment_type = PatSizeChart.GARMENT_ACCESSORY
        pattern.size_chart.save(update_fields=["garment_type"])
        piece = add_pattern_piece(pattern, code="devant", name="Devant")
        with pytest.raises(ValidationError):
            generate_piece_geometry(
                piece, size="M", graded_measurements={"tour_poitrine": Decimal(96)}
            )
