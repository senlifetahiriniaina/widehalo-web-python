"""Tests de proprietes (couche 13 du CDC, §8) : linearite de l'eclatement
de nomenclature (`apps.mrp.services.bom.explode`) sur des quantites et taux
de chute generes arbitrairement par Hypothesis. 1000 exemples par test.

`_explode_level()` ne fait aucun arrondi/quantization propre : chaque
quantite planifiee est `base_qty * qty_needed * (1 + waste_pct/100)`, une
simple multiplication de `Decimal`. La linearite est donc exacte (pas
seulement approximative a une tolerance pres) tant que la precision par
defaut du contexte `decimal` (28 chiffres significatifs) n'est pas depassee
— ce que les bornes ci-dessous garantissent."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.mrp.models import MrpBom
from apps.mrp.services.bom import activate_bom, add_bom_line, create_bom, explode

pytestmark = pytest.mark.django_db

# qty compatible avec MrpBomLine.qty (DecimalField(18,4)) : amplitude
# raisonnable pour une quantite de composant/produit fini.
_QTY = st.decimals(
    min_value=Decimal("0.0001"),
    max_value=Decimal("1000"),
    places=4,
    allow_nan=False,
    allow_infinity=False,
)
_WASTE_PCT = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("50"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
# Facteur d'echelle k : entier borne pour rester lisible ; le produit
# qty * k * (1 + waste/100) doit rester tres en-dessous du plafond de
# precision du contexte Decimal (28 chiffres significatifs par defaut).
_SCALE_K = st.integers(min_value=1, max_value=50)


def _single_line_bom(line_qty: Decimal, waste_pct: Decimal) -> tuple[Tenant, MrpBom]:
    tenant = Tenant.objects.create(
        code=f"HYP-MRP-{uuid.uuid4().hex[:12]}", name="Hypothesis MRP Tenant"
    )
    with use_tenant(tenant.id):
        product_id = uuid.uuid4()
        component_id = uuid.uuid4()
        bom = create_bom(tenant=tenant, code="BOM-HYP", product_template_id=product_id)
        add_bom_line(bom, component_template_id=component_id, qty=line_qty, waste_pct=waste_pct)
        activate_bom(bom)
    return tenant, bom


@pytest.mark.slow
@given(line_qty=_QTY, waste_pct=_WASTE_PCT, base_requested_qty=_QTY, k=_SCALE_K)
@settings(
    max_examples=1000,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
def test_explode_scales_linearly_with_requested_qty(
    line_qty: Decimal, waste_pct: Decimal, base_requested_qty: Decimal, k: int
) -> None:
    """A `waste_pct` fixe, exploser une nomenclature a mono-composant pour
    `qty * k` doit produire exactement `k` fois la quantite obtenue pour
    `qty` seule — `explode()` n'introduit aucun arrondi propre, la linearite
    est donc verifiee a l'egalite exacte, pas a une tolerance pres."""
    tenant, bom = _single_line_bom(line_qty, waste_pct)
    with use_tenant(tenant.id):
        base_rows = explode(bom, base_requested_qty)
        scaled_rows = explode(bom, base_requested_qty * k)

        assert len(base_rows) == len(scaled_rows) == 1
        assert scaled_rows[0]["qty"] == base_rows[0]["qty"] * k


@pytest.mark.slow
@given(line_qty=_QTY, waste_pct=_WASTE_PCT, requested_qty=_QTY)
@settings(
    max_examples=1000,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
def test_explode_matches_closed_form_with_waste(
    line_qty: Decimal, waste_pct: Decimal, requested_qty: Decimal
) -> None:
    """Verification independante de la formule elle-meme (pas seulement de
    sa linearite interne) : la quantite exploded doit correspondre exactement
    a `line_qty * requested_qty * (1 + waste_pct/100)`, la formule
    documentee par `_explode_level()`."""
    tenant, bom = _single_line_bom(line_qty, waste_pct)
    with use_tenant(tenant.id):
        rows = explode(bom, requested_qty)

        expected = line_qty * requested_qty * (Decimal(1) + waste_pct / Decimal(100))
        assert rows[0]["qty"] == expected
