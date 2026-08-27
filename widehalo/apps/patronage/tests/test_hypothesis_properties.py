"""Tests de proprietes (couche 13 du CDC, §8) : RG-PAT-2 (coherence/monotonie
de la gradation), generalisation par Hypothesis des cas fixes de
`test_grading.py::test_fixed_increment_over_seven_sizes_is_monotonic` et
`::test_inconsistent_rule_raises_validation_error`. 1000 exemples par test.

`apply_grading()` en mode `increment_fixe` applique, a partir de la taille
de base, `current +/- rule.value` a chaque pas de taille (cf.
`_apply_step()`). Pour une grille de tailles ordonnee et une valeur
d'increment >= 0, la suite obtenue est necessairement croissante (large) des
deux cotes de la taille de base : la propriete "succes garanti" est donc
construite en generant uniquement des increments non-negatifs. A l'inverse,
une valeur d'increment strictement negative rend la suite necessairement
decroissante d'au moins un cote (des lors qu'il existe au moins une taille de
part et d'autre de la taille de base), ce qui doit toujours declencher la
ValidationError de `_check_monotonic()`."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

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

_ALL_SIZES = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL", "4XL"]

# Base value compatible avec PatSizeChartValue.value (DecimalField(18,4)) :
# une mesure corporelle plausible en cm.
_BASE_VALUE = st.decimals(
    min_value=Decimal("10"),
    max_value=Decimal("200"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
# Increment non-negatif (branche "doit toujours reussir").
_NONNEG_INCREMENT = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("20"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
# Increment strictement negatif (branche "doit toujours lever").
_NEGATIVE_INCREMENT = st.decimals(
    min_value=Decimal("-20"),
    max_value=Decimal("-0.01"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
# Sous-liste de tailles (>=3, pour garantir au moins une taille de chaque
# cote de la base) et index de base strictement a l'interieur.
_SIZE_COUNT = st.integers(min_value=3, max_value=len(_ALL_SIZES))


def _size_chart_with_rule(
    sizes: list[str], base_index: int, base_value: Decimal, increment: Decimal
) -> PatSizeChart:
    tenant = Tenant.objects.create(
        code=f"HYP-PAT-{uuid.uuid4().hex[:12]}", name="Hypothesis Patronage Tenant"
    )
    with use_tenant(tenant.id):
        base_size = sizes[base_index]
        chart = PatSizeChart.objects.create(
            tenant=tenant,
            code="HYP-CHART",
            name="Grille Hypothesis",
            garment_type=PatSizeChart.GARMENT_SHIRT,
            sizes=sizes,
            base_size=base_size,
        )
        point = PatMeasurementPoint.objects.create(tenant=tenant, code="pt", name="Point mesure")
        PatSizeChartValue.objects.create(
            tenant=tenant,
            size_chart=chart,
            measurement_point=point,
            size=base_size,
            value=base_value,
        )
        PatGradingRule.objects.create(
            tenant=tenant,
            size_chart=chart,
            measurement_point=point,
            mode=PatGradingRule.MODE_FIXED,
            value=increment,
            from_size=sizes[0],
            to_size=sizes[-1],
        )
    return chart


@pytest.mark.slow
@given(
    size_count=_SIZE_COUNT,
    base_offset=st.integers(min_value=1, max_value=1000),
    base_value=_BASE_VALUE,
    increment=_NONNEG_INCREMENT,
)
@settings(
    max_examples=1000,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
def test_nonnegative_increment_is_always_monotonic(
    size_count: int, base_offset: int, base_value: Decimal, increment: Decimal
) -> None:
    """RG-PAT-2 : pour toute grille de tailles et tout increment fixe
    non-negatif, `apply_grading()` doit toujours reussir (jamais lever) et
    produire une suite de valeurs triee dans l'ordre des tailles."""
    sizes = _ALL_SIZES[:size_count]
    base_index = base_offset % size_count
    chart = _size_chart_with_rule(sizes, base_index, base_value, increment)
    with use_tenant(chart.tenant_id):
        result = apply_grading(chart)
        ordered = [result["pt"][s] for s in sizes]
        assert ordered == sorted(ordered)


@pytest.mark.slow
@given(
    size_count=_SIZE_COUNT,
    base_offset=st.integers(min_value=1, max_value=1000),
    base_value=_BASE_VALUE,
    increment=_NEGATIVE_INCREMENT,
)
@settings(
    max_examples=1000,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
def test_negative_increment_always_raises(
    size_count: int, base_offset: int, base_value: Decimal, increment: Decimal
) -> None:
    """RG-PAT-2 : la meme construction avec un increment strictement negatif
    doit toujours etre rejetee par `_check_monotonic()` — au moins une des
    deux directions (vers la taille de base ou en s'en eloignant) devient
    necessairement decroissante des lors qu'il existe une taille de chaque
    cote de la base (garanti par `_SIZE_COUNT` >= 3 et un `base_index`
    strictement a l'interieur des bornes)."""
    sizes = _ALL_SIZES[:size_count]
    # base_index strictement a l'interieur (ni premiere ni derniere taille) :
    # garantit au moins un pas vers le haut ET un pas vers le bas.
    base_index = 1 + (base_offset % (size_count - 2))
    chart = _size_chart_with_rule(sizes, base_index, base_value, increment)
    with use_tenant(chart.tenant_id), pytest.raises(ValidationError):
        apply_grading(chart)
