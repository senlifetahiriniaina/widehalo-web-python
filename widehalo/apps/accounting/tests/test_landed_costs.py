"""A17 — Couts d'importation (landed costs), ACC-IMP : calculateur de
repartition de frais additionnels entre les lignes d'un lot d'achat
importe. Cf. docstring de `services/landed_costs.py` pour le perimetre
explicitement exclu (aucune ecriture postee en comptabilite generale) et
pour l'integration stock reelle desormais cablee dans `finalize_batch`."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounting.models import AccLandedCostBatch
from apps.accounting.services.landed_costs import (
    add_cost_component,
    add_landed_cost_line,
    create_landed_cost_batch,
    finalize_batch,
    landed_cost_report,
)
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.stocks.tests.factories import StkValuationLayerFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    t = Tenant.objects.create(code="ACC-A17", name="Accounting A17 Tenant")
    with use_tenant(t.id):
        yield t


def _make_batch(tenant, *, allocation_method):
    return create_landed_cost_batch(
        tenant=tenant,
        label="Import tissu coton — conteneur #4521",
        date=dt.date(2026, 3, 1),
        allocation_method=allocation_method,
    )


def test_add_line_recomputes_total_purchase_value(tenant):
    batch = _make_batch(tenant, allocation_method=AccLandedCostBatch.METHOD_BY_VALUE)
    add_landed_cost_line(
        batch,
        description="Tissu coton ecru, 500m",
        qty=Decimal(500),
        purchase_value_mga=Decimal("3000000"),
    )
    batch.refresh_from_db()
    assert batch.total_purchase_value_mga == Decimal("3000000")

    add_landed_cost_line(
        batch,
        description="Tissu polyester, 200m",
        qty=Decimal(200),
        purchase_value_mga=Decimal("1000000"),
    )
    batch.refresh_from_db()
    assert batch.total_purchase_value_mga == Decimal("4000000")


def test_by_value_allocation_hand_calculated(tenant):
    """2 lignes, 2 composants de cout — verification precise de la formule.

    Ligne A : achat 3 000 000 MGA, qty 500.
    Ligne B : achat 1 000 000 MGA, qty 200.
    Total achat = 4 000 000 MGA.
    Composants : fret 400 000 + assurance 100 000 = 500 000 MGA total.

    Cle A = 3 000 000 / 4 000 000 = 0.75 -> alloue = 0.75 * 500 000 = 375 000
    Cle B = 1 000 000 / 4 000 000 = 0.25 -> alloue = 0.25 * 500 000 = 125 000

    Landed total A = 3 000 000 + 375 000 = 3 375 000 -> unitaire = 3 375 000/500 = 6 750
    Landed total B = 1 000 000 + 125 000 = 1 125 000 -> unitaire = 1 125 000/200 = 5 625
    """
    batch = _make_batch(tenant, allocation_method=AccLandedCostBatch.METHOD_BY_VALUE)
    add_landed_cost_line(
        batch, description="Ligne A", qty=Decimal(500), purchase_value_mga=Decimal("3000000")
    )
    add_landed_cost_line(
        batch, description="Ligne B", qty=Decimal(200), purchase_value_mga=Decimal("1000000")
    )
    add_cost_component(batch, label="Fret maritime", amount_mga=Decimal("400000"))
    add_cost_component(batch, label="Assurance transport", amount_mga=Decimal("100000"))

    rows = landed_cost_report(batch)
    assert len(rows) == 2
    row_a, row_b = rows

    assert row_a["allocation_key_pct"] == Decimal("0.75")
    assert row_a["allocated_cost_mga"] == Decimal("375000")
    assert row_a["landed_total_mga"] == Decimal("3375000")
    assert row_a["landed_unit_cost_mga"] == Decimal("6750")

    assert row_b["allocation_key_pct"] == Decimal("0.25")
    assert row_b["allocated_cost_mga"] == Decimal("125000")
    assert row_b["landed_total_mga"] == Decimal("1125000")
    assert row_b["landed_unit_cost_mga"] == Decimal("5625")


def test_by_weight_allocation(tenant):
    batch = _make_batch(tenant, allocation_method=AccLandedCostBatch.METHOD_BY_WEIGHT)
    add_landed_cost_line(
        batch,
        description="Ligne lourde",
        qty=Decimal(10),
        purchase_value_mga=Decimal("100000"),
        weight_kg=Decimal("300"),
    )
    add_landed_cost_line(
        batch,
        description="Ligne legere",
        qty=Decimal(10),
        purchase_value_mga=Decimal("100000"),
        weight_kg=Decimal("100"),
    )
    add_cost_component(batch, label="Fret maritime", amount_mga=Decimal("200000"))
    add_cost_component(batch, label="Douane", amount_mga=Decimal("200000"))

    rows = landed_cost_report(batch)
    # total_weight = 400 ; total_cost = 400000
    row_heavy, row_light = rows
    assert row_heavy["allocation_key_pct"] == Decimal("0.75")
    assert row_heavy["allocated_cost_mga"] == Decimal("300000")
    assert row_light["allocation_key_pct"] == Decimal("0.25")
    assert row_light["allocated_cost_mga"] == Decimal("100000")


def test_by_weight_missing_data_raises(tenant):
    batch = _make_batch(tenant, allocation_method=AccLandedCostBatch.METHOD_BY_WEIGHT)
    add_landed_cost_line(
        batch,
        description="Sans poids",
        qty=Decimal(10),
        purchase_value_mga=Decimal("100000"),
    )
    add_cost_component(batch, label="Fret", amount_mga=Decimal("10000"))

    with pytest.raises(ValidationError):
        landed_cost_report(batch)


def test_by_quantity_allocation(tenant):
    batch = _make_batch(tenant, allocation_method=AccLandedCostBatch.METHOD_BY_QUANTITY)
    add_landed_cost_line(
        batch, description="Ligne 1", qty=Decimal(300), purchase_value_mga=Decimal("100000")
    )
    add_landed_cost_line(
        batch, description="Ligne 2", qty=Decimal(100), purchase_value_mga=Decimal("100000")
    )
    add_cost_component(batch, label="Manutention portuaire", amount_mga=Decimal("40000"))

    rows = landed_cost_report(batch)
    row_1, row_2 = rows
    assert row_1["allocation_key_pct"] == Decimal("0.75")
    assert row_1["allocated_cost_mga"] == Decimal("30000")
    assert row_2["allocation_key_pct"] == Decimal("0.25")
    assert row_2["allocated_cost_mga"] == Decimal("10000")


def test_division_by_zero_qty_returns_none_unit_cost(tenant):
    """Une ligne avec `qty=0` ne doit jamais lever `ZeroDivisionError` :
    `landed_unit_cost_mga` doit rester calculable ailleurs et retourner
    `None` uniquement pour cette ligne."""
    batch = _make_batch(tenant, allocation_method=AccLandedCostBatch.METHOD_BY_VALUE)
    add_landed_cost_line(
        batch,
        description="Echantillon gratuit",
        qty=Decimal(0),
        purchase_value_mga=Decimal("50000"),
    )
    add_landed_cost_line(
        batch, description="Ligne normale", qty=Decimal(10), purchase_value_mga=Decimal("50000")
    )
    add_cost_component(batch, label="Fret", amount_mga=Decimal("10000"))

    rows = landed_cost_report(batch)
    row_zero_qty, row_normal = rows
    assert row_zero_qty["qty"] == Decimal(0)
    assert row_zero_qty["allocated_cost_mga"] == Decimal("5000")
    assert row_zero_qty["landed_total_mga"] == Decimal("55000")
    assert row_zero_qty["landed_unit_cost_mga"] is None
    assert row_normal["landed_unit_cost_mga"] is not None


def test_zero_total_purchase_value_returns_none_allocation(tenant):
    """Lot dont toutes les lignes ont une valeur d'achat nulle (methode
    `by_value`) : la cle d'allocation, le cout alloue, le total debarque et
    le cout unitaire doivent tous rester `None` plutot que de lever."""
    batch = _make_batch(tenant, allocation_method=AccLandedCostBatch.METHOD_BY_VALUE)
    add_landed_cost_line(
        batch, description="Gratuit", qty=Decimal(10), purchase_value_mga=Decimal(0)
    )
    add_cost_component(batch, label="Fret", amount_mga=Decimal("10000"))

    rows = landed_cost_report(batch)
    row = rows[0]
    assert row["allocation_key_pct"] is None
    assert row["allocated_cost_mga"] is None
    assert row["landed_total_mga"] is None
    assert row["landed_unit_cost_mga"] is None


def test_add_line_rejected_on_finalized_batch(tenant):
    batch = _make_batch(tenant, allocation_method=AccLandedCostBatch.METHOD_BY_VALUE)
    add_landed_cost_line(
        batch, description="Ligne", qty=Decimal(10), purchase_value_mga=Decimal("100000")
    )
    finalize_batch(batch)

    with pytest.raises(ValidationError):
        add_landed_cost_line(
            batch, description="Autre ligne", qty=Decimal(5), purchase_value_mga=Decimal("50000")
        )


def test_add_cost_component_rejected_on_finalized_batch(tenant):
    batch = _make_batch(tenant, allocation_method=AccLandedCostBatch.METHOD_BY_VALUE)
    add_landed_cost_line(
        batch, description="Ligne", qty=Decimal(10), purchase_value_mga=Decimal("100000")
    )
    finalize_batch(batch)

    with pytest.raises(ValidationError):
        add_cost_component(batch, label="Fret tardif", amount_mga=Decimal("1000"))


def test_double_finalization_rejected(tenant):
    batch = _make_batch(tenant, allocation_method=AccLandedCostBatch.METHOD_BY_VALUE)
    finalize_batch(batch)

    with pytest.raises(ValidationError):
        finalize_batch(batch)


# ---------------------------------------------------------------------------
# Chantier de durcissement retroactif : integration stock reelle a la
# finalisation (`stocks.services.public.apply_landed_cost_to_valuation`).
# ---------------------------------------------------------------------------


def test_finalize_batch_revalues_stock_for_lines_with_variant_id(tenant):
    variant_id = uuid.uuid4()
    layer = StkValuationLayerFactory(
        tenant=tenant,
        variant_id=variant_id,
        qty=Decimal(500),
        remaining_qty=Decimal(500),
        value_mga=Decimal("3000000"),
        remaining_value_mga=Decimal("3000000"),
    )
    batch = _make_batch(tenant, allocation_method=AccLandedCostBatch.METHOD_BY_VALUE)
    add_landed_cost_line(
        batch,
        description="Tissu coton",
        qty=Decimal(500),
        purchase_value_mga=Decimal("3000000"),
        variant_id=variant_id,
    )
    add_cost_component(batch, label="Fret maritime", amount_mga=Decimal("375000"))

    finalize_batch(batch)

    layer.refresh_from_db()
    # Seule ligne du lot : elle recoit l'integralite du cout alloue.
    assert layer.remaining_value_mga == Decimal("3375000")
    assert layer.value_mga == Decimal("3375000")


def test_finalize_batch_leaves_lines_without_variant_id_untouched(tenant):
    """Une ligne sans `variant_id` (frais general non rattache a un
    article) n'a rien a revaloriser cote stock — `finalize_batch` ne doit
    ni lever ni creer de couche de valorisation fantome."""
    batch = _make_batch(tenant, allocation_method=AccLandedCostBatch.METHOD_BY_VALUE)
    add_landed_cost_line(
        batch, description="Frais general", qty=Decimal(1), purchase_value_mga=Decimal("100000")
    )
    add_cost_component(batch, label="Fret", amount_mga=Decimal("10000"))

    finalized = finalize_batch(batch)

    assert finalized.state == AccLandedCostBatch.STATE_FINALIZED


def test_finalize_batch_is_noop_on_stock_for_variant_without_active_layers(tenant):
    """`apply_landed_cost_to_valuation` renvoie `False` (jamais une
    exception) quand la variante n'a aucune couche de valorisation active
    — `finalize_batch` doit rester silencieux dans ce cas."""
    batch = _make_batch(tenant, allocation_method=AccLandedCostBatch.METHOD_BY_VALUE)
    add_landed_cost_line(
        batch,
        description="Variante sans stock receptionne",
        qty=Decimal(10),
        purchase_value_mga=Decimal("100000"),
        variant_id=uuid.uuid4(),
    )
    add_cost_component(batch, label="Fret", amount_mga=Decimal("10000"))

    finalized = finalize_batch(batch)

    assert finalized.state == AccLandedCostBatch.STATE_FINALIZED
