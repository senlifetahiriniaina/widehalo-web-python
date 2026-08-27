"""T2 (couches 4-5 du CDC, §8) : contraintes structurelles/d'interdependance
au niveau base pour `patronage` — `UniqueConstraint` (grille de tailles,
mesures de piece, geometrie, consommation) et comportement `on_delete`
(PROTECT/CASCADE/SET_NULL) de chaque FK du modele. Ces contraintes existent
deja dans `models.py` mais n'etaient couvertes par aucun test avant ce lot.

RLS (isolation tenant) est hors-perimetre (couverte ailleurs)."""

from __future__ import annotations

import pytest
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.db.utils import IntegrityError

from apps.core.tests.factories import TenantFactory, UserFactory
from apps.core.tests.utils import use_tenant
from apps.patronage.models import (
    PatConsumption,
    PatMarker,
    PatPatternPiece,
    PatPieceGeometry,
    PatPieceMeasure,
    PatSizeChartValue,
    PatTechPack,
)
from apps.patronage.tests.factories import (
    PatConsumptionFactory,
    PatGradingRuleFactory,
    PatMarkerFactory,
    PatPatternFactory,
    PatPatternPieceFactory,
    PatPieceGeometryFactory,
    PatPieceMeasureFactory,
    PatSizeChartValueFactory,
    PatTechPackFactory,
)

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------
# UniqueConstraint
# --------------------------------------------------------------------------


def test_size_chart_value_unique_per_chart_point_and_size() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        value = PatSizeChartValueFactory(tenant=tenant, size="M")

        with pytest.raises(IntegrityError), transaction.atomic():
            PatSizeChartValue.objects.create(
                tenant=tenant,
                size_chart=value.size_chart,
                measurement_point=value.measurement_point,
                size="M",
                value=51,
            )


def test_piece_geometry_unique_per_piece_and_size() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        geometry = PatPieceGeometryFactory(tenant=tenant, size="M")

        with pytest.raises(IntegrityError), transaction.atomic():
            PatPieceGeometry.objects.create(tenant=tenant, piece=geometry.piece, size="M")


def test_piece_measure_unique_per_piece_point_and_size() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        measure = PatPieceMeasureFactory(tenant=tenant, size="M")

        with pytest.raises(IntegrityError), transaction.atomic():
            PatPieceMeasure.objects.create(
                tenant=tenant,
                piece=measure.piece,
                measurement_point=measure.measurement_point,
                size="M",
                value=51,
            )


def test_consumption_unique_per_pattern_size_and_material() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        consumption = PatConsumptionFactory(tenant=tenant, size="M")

        with pytest.raises(IntegrityError), transaction.atomic():
            PatConsumption.objects.create(
                tenant=tenant,
                pattern=consumption.pattern,
                size="M",
                material_variant_id=consumption.material_variant_id,
                width_cm=150,
            )


# --------------------------------------------------------------------------
# on_delete=PROTECT
# --------------------------------------------------------------------------


def test_size_chart_cannot_be_deleted_while_referenced_by_a_pattern() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        pattern = PatPatternFactory(tenant=tenant)
        size_chart = pattern.size_chart

        with pytest.raises(ProtectedError):
            size_chart.delete()


def test_measurement_point_cannot_be_deleted_while_referenced_by_a_size_chart_value() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        value = PatSizeChartValueFactory(tenant=tenant)
        measurement_point = value.measurement_point

        with pytest.raises(ProtectedError):
            measurement_point.delete()


def test_measurement_point_cannot_be_deleted_while_referenced_by_a_grading_rule() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        rule = PatGradingRuleFactory(tenant=tenant)
        measurement_point = rule.measurement_point

        with pytest.raises(ProtectedError):
            measurement_point.delete()


def test_measurement_point_cannot_be_deleted_while_referenced_by_a_piece_measure() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        measure = PatPieceMeasureFactory(tenant=tenant)
        measurement_point = measure.measurement_point

        with pytest.raises(ProtectedError):
            measurement_point.delete()


def test_document_cannot_be_deleted_while_referenced_by_a_tech_pack() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        tech_pack = PatTechPackFactory(tenant=tenant)
        document = tech_pack.document

        with pytest.raises(ProtectedError):
            document.delete()


# --------------------------------------------------------------------------
# on_delete=CASCADE
# --------------------------------------------------------------------------


def test_deleting_a_pattern_cascades_to_its_pieces() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        piece = PatPatternPieceFactory(tenant=tenant)
        pattern = piece.pattern
        piece_id = piece.id

        pattern.delete()

        assert not PatPatternPiece.objects.filter(pk=piece_id).exists()


def test_deleting_a_piece_cascades_to_its_geometries() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        geometry = PatPieceGeometryFactory(tenant=tenant)
        piece = geometry.piece
        geometry_id = geometry.id

        piece.delete()

        assert not PatPieceGeometry.objects.filter(pk=geometry_id).exists()


def test_deleting_a_piece_cascades_to_its_measures() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        measure = PatPieceMeasureFactory(tenant=tenant)
        piece = measure.piece
        measure_id = measure.id

        piece.delete()

        assert not PatPieceMeasure.objects.filter(pk=measure_id).exists()


def test_deleting_a_pattern_cascades_to_its_consumptions() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        consumption = PatConsumptionFactory(tenant=tenant)
        pattern = consumption.pattern
        consumption_id = consumption.id

        pattern.delete()

        assert not PatConsumption.objects.filter(pk=consumption_id).exists()


def test_deleting_a_pattern_cascades_to_its_markers() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        marker = PatMarkerFactory(tenant=tenant)
        pattern = marker.pattern
        marker_id = marker.id

        pattern.delete()

        assert not PatMarker.objects.filter(pk=marker_id).exists()


def test_deleting_a_pattern_cascades_to_its_tech_packs() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        tech_pack = PatTechPackFactory(tenant=tenant)
        pattern = tech_pack.pattern
        tech_pack_id = tech_pack.id

        pattern.delete()

        assert not PatTechPack.objects.filter(pk=tech_pack_id).exists()


def test_deleting_a_size_chart_cascades_to_its_values() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        value = PatSizeChartValueFactory(tenant=tenant)
        size_chart = value.size_chart
        value_id = value.id

        size_chart.delete()

        assert not PatSizeChartValue.objects.filter(pk=value_id).exists()


# --------------------------------------------------------------------------
# on_delete=SET_NULL
# --------------------------------------------------------------------------


def test_deleting_a_parent_pattern_nullifies_the_version() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        parent_pattern = PatPatternFactory(tenant=tenant)
        version = PatPatternFactory(tenant=tenant, parent_pattern=parent_pattern)

        parent_pattern.delete()
        version.refresh_from_db()

        assert version.parent_pattern_id is None


def test_deleting_a_designer_nullifies_the_pattern() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        designer = UserFactory()
        pattern = PatPatternFactory(tenant=tenant, designer=designer)

        designer.delete()
        pattern.refresh_from_db()

        assert pattern.designer_id is None
