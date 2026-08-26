from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.patronage.models import (
    PatGradingRule,
    PatMeasurementPoint,
    PatSizeChart,
    PatSizeChartValue,
)
from apps.patronage.services.grading import apply_grading

pytestmark = pytest.mark.django_db


SEVEN_SIZES = ["XS", "S", "M", "L", "XL", "XXL", "XXXL"]


@pytest.fixture
def grading_setup():
    tenant = Tenant.objects.create(code="PAT-GRD", name="Patronage Grading Tenant")
    with use_tenant(tenant.id):
        chart = PatSizeChart.objects.create(
            tenant=tenant,
            code="CHEMISE-H",
            name="Chemise homme",
            garment_type=PatSizeChart.GARMENT_SHIRT,
            sizes=SEVEN_SIZES,
            base_size="XS",
        )
        chest = PatMeasurementPoint.objects.create(
            tenant=tenant, code="tour_poitrine", name="Tour de poitrine"
        )
        PatSizeChartValue.objects.create(
            tenant=tenant, size_chart=chart, measurement_point=chest, size="XS", value=Decimal(90)
        )
        return tenant, chart, chest


def test_fixed_increment_over_seven_sizes_is_monotonic(grading_setup) -> None:
    tenant, chart, chest = grading_setup
    with use_tenant(tenant.id):
        PatGradingRule.objects.create(
            tenant=tenant,
            size_chart=chart,
            measurement_point=chest,
            mode=PatGradingRule.MODE_FIXED,
            value=Decimal(4),
            from_size="XS",
            to_size="XXXL",
        )
        result = apply_grading(chart)
        values = result["tour_poitrine"]
        assert values["XS"] == Decimal(90)
        assert values["S"] == Decimal(94)
        assert values["XXXL"] == Decimal(90 + 4 * 6)
        ordered = [values[s] for s in SEVEN_SIZES]
        assert ordered == sorted(ordered)


def test_progressive_increment_changes_step_by_range(grading_setup) -> None:
    tenant, chart, chest = grading_setup
    with use_tenant(tenant.id):
        PatGradingRule.objects.create(
            tenant=tenant,
            size_chart=chart,
            measurement_point=chest,
            mode=PatGradingRule.MODE_PROGRESSIVE,
            value=Decimal(2),
            from_size="XS",
            to_size="L",
        )
        PatGradingRule.objects.create(
            tenant=tenant,
            size_chart=chart,
            measurement_point=chest,
            mode=PatGradingRule.MODE_PROGRESSIVE,
            value=Decimal(3),
            from_size="L",
            to_size="XXXL",
        )
        result = apply_grading(chart)
        values = result["tour_poitrine"]
        # XS->S->M->L : +2 x3 = 96 ; L->XL : +3
        assert values["L"] == Decimal(96)
        assert values["XL"] == Decimal(99)


def test_formula_mode_derives_from_another_measurement_point(grading_setup) -> None:
    tenant, chart, chest = grading_setup
    with use_tenant(tenant.id):
        waist = PatMeasurementPoint.objects.create(
            tenant=tenant, code="tour_taille", name="Tour de taille"
        )
        PatSizeChartValue.objects.create(
            tenant=tenant, size_chart=chart, measurement_point=waist, size="XS", value=Decimal(70)
        )
        hip = PatMeasurementPoint.objects.create(
            tenant=tenant, code="tour_bassin", name="Tour de bassin"
        )
        PatGradingRule.objects.create(
            tenant=tenant,
            size_chart=chart,
            measurement_point=waist,
            mode=PatGradingRule.MODE_FIXED,
            value=Decimal(4),
            from_size="XS",
            to_size="XXXL",
        )
        PatGradingRule.objects.create(
            tenant=tenant,
            size_chart=chart,
            measurement_point=hip,
            mode=PatGradingRule.MODE_FORMULA,
            formula="tour_taille * 1.28",
            from_size="XS",
            to_size="XXXL",
        )
        result = apply_grading(chart)
        assert result["tour_bassin"]["XS"] == Decimal(70) * Decimal("1.28")


def test_inconsistent_rule_raises_validation_error(grading_setup) -> None:
    tenant, chart, chest = grading_setup
    with use_tenant(tenant.id):
        PatGradingRule.objects.create(
            tenant=tenant,
            size_chart=chart,
            measurement_point=chest,
            mode=PatGradingRule.MODE_FIXED,
            value=Decimal(-4),
            from_size="XS",
            to_size="XXXL",
        )
        with pytest.raises(ValidationError):
            apply_grading(chart)


def test_percentage_mode_is_multiplicative(grading_setup) -> None:
    tenant, chart, chest = grading_setup
    with use_tenant(tenant.id):
        PatGradingRule.objects.create(
            tenant=tenant,
            size_chart=chart,
            measurement_point=chest,
            mode=PatGradingRule.MODE_PERCENTAGE,
            value=Decimal(10),
            from_size="XS",
            to_size="XXXL",
        )
        result = apply_grading(chart)
        assert result["tour_poitrine"]["S"] == Decimal(90) * Decimal("1.1")
