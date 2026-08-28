"""RG-STK-7 (defauts et etats qualite, ST3 du sous-sequencement `stocks`
— cf. plan) : garde XOR quant/lot, relocalisation physique pour
`defaut_majeur`/`rebut` uniquement, valeur conservee apres relocalisation
(ajustement `_is_valuation_internal` de `services.moves`)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLocation, StkLot, StkMove, StkQualityState, StkValuationLayer
from apps.stocks.services.moves import create_move, validate_move
from apps.stocks.services.quality import apply_quality_decision, set_quality_state
from apps.stocks.services.quants import get_quant, on_hand_qty
from apps.stocks.services.warehouses import create_location, create_warehouse

pytestmark = pytest.mark.django_db


@pytest.fixture
def quality_setup():
    tenant = Tenant.objects.create(code="STK-QUA-T", name="Stocks Quality Tenant")
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-01", name="Entrepot principal")
        internal = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="A1",
            name="Rayon A1",
            type=StkLocation.TYPE_INTERNE,
        )
        supplier = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="FRS",
            name="Fournisseur",
            type=StkLocation.TYPE_FOURNISSEUR,
        )
        rebut = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="REB",
            name="Rebut",
            type=StkLocation.TYPE_REBUT,
            is_scrap=True,
        )
        variant_id = uuid.uuid4()
        reception = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal("100"),
            uom="m",
            location_from=supplier,
            location_to=internal,
            date=dt.date.today(),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost_mga=Decimal("1000"),
        )
        validate_move(reception)
        quant = get_quant(variant_id, internal)
        return tenant, internal, rebut, variant_id, quant


def test_set_quality_state_refuses_neither_quant_nor_lot(quality_setup) -> None:
    tenant, *_rest = quality_setup
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        set_quality_state(tenant=tenant, state=StkQualityState.STATE_CONFORME)


def test_set_quality_state_refuses_both_quant_and_lot(quality_setup) -> None:
    tenant, _internal, _rebut, _variant_id, quant = quality_setup
    with use_tenant(tenant.id):
        lot = StkLot.objects.create(tenant=tenant, variant_id=quant.variant_id, name="LOT-1")
        with pytest.raises(ValidationError):
            set_quality_state(
                tenant=tenant, quant=quant, lot=lot, state=StkQualityState.STATE_CONFORME
            )


def test_set_quality_state_accepts_quant_only(quality_setup) -> None:
    tenant, _internal, _rebut, _variant_id, quant = quality_setup
    with use_tenant(tenant.id):
        state = set_quality_state(tenant=tenant, quant=quant, state=StkQualityState.STATE_CONFORME)
        assert state.decided_at is not None


@pytest.mark.parametrize(
    "state",
    [
        StkQualityState.STATE_CONFORME,
        StkQualityState.STATE_DEFAUT_MINEUR,
        StkQualityState.STATE_EN_QUARANTAINE,
        StkQualityState.STATE_DECLASSE,
    ],
)
def test_apply_quality_decision_creates_no_move_for_non_relocation_states(
    quality_setup, state
) -> None:
    tenant, _internal, rebut, _variant_id, quant = quality_setup
    with use_tenant(tenant.id):
        quality_state = set_quality_state(tenant=tenant, quant=quant, state=state)
        move = apply_quality_decision(quality_state, quarantine_or_scrap_location=rebut)
        assert move is None


def test_apply_quality_decision_relocates_full_quant_qty_for_rebut_by_default(
    quality_setup,
) -> None:
    tenant, internal, rebut, variant_id, quant = quality_setup
    with use_tenant(tenant.id):
        assert on_hand_qty(variant_id) == Decimal("100")
        quality_state = set_quality_state(
            tenant=tenant, quant=quant, state=StkQualityState.STATE_REBUT
        )
        move = apply_quality_decision(quality_state, quarantine_or_scrap_location=rebut)

        assert move is not None
        assert move.state == StkMove.STATE_DONE
        assert move.qty == Decimal("100")
        assert move.location_from_id == internal.id
        assert move.location_to_id == rebut.id


def test_apply_quality_decision_relocates_only_defect_qty_when_specified(quality_setup) -> None:
    tenant, internal, rebut, variant_id, quant = quality_setup
    with use_tenant(tenant.id):
        quality_state = set_quality_state(
            tenant=tenant,
            quant=quant,
            state=StkQualityState.STATE_DEFAUT_MAJEUR,
            defect_qty=Decimal("15"),
        )
        move = apply_quality_decision(quality_state, quarantine_or_scrap_location=rebut)

        assert move is not None
        assert move.qty == Decimal("15")
        # Le solde interne recule de 15, le rebut n'est pas compte dans la
        # vue "on hand" (emplacements internes uniquement).
        assert on_hand_qty(variant_id) == Decimal("85")


def test_apply_quality_decision_relocation_keeps_value_valorized_at_rebut(
    quality_setup,
) -> None:
    """ "Restant valorisee jusqu'a decision" (RG-STK-7) : verifie a la main
    que la valeur totale des couches `StkValuationLayer` du produit ne
    change PAS apres relocalisation vers un emplacement `TYPE_REBUT`
    (transfert interne->interne au sens valorisation, cf. ajustement
    `_is_valuation_internal` de `services.moves`) — la couche de reception
    initiale (100 unites a 1000 MGA/u = 100 000 MGA) reste intacte, seul le
    quant change d'emplacement."""
    tenant, internal, rebut, variant_id, quant = quality_setup
    with use_tenant(tenant.id):
        layers_before = list(StkValuationLayer.objects.filter(variant_id=variant_id))
        assert len(layers_before) == 1
        assert layers_before[0].remaining_value_mga == Decimal("100000.0000")

        quality_state = set_quality_state(
            tenant=tenant, quant=quant, state=StkQualityState.STATE_REBUT
        )
        apply_quality_decision(quality_state, quarantine_or_scrap_location=rebut)

        # Aucune nouvelle couche creee, aucune couche consommee : le
        # transfert vers `TYPE_REBUT` est traite comme interne->interne au
        # sens valorisation.
        layers_after = list(StkValuationLayer.objects.filter(variant_id=variant_id))
        assert len(layers_after) == 1
        assert layers_after[0].remaining_value_mga == Decimal("100000.0000")

        rebut_quant = get_quant(variant_id, rebut)
        assert rebut_quant is not None
        assert rebut_quant.qty == Decimal("100")
        assert rebut_quant.value_mga == Decimal("100000.0000")

        internal_quant = get_quant(variant_id, internal)
        assert internal_quant is not None
        assert internal_quant.qty == Decimal("0")
        assert internal_quant.value_mga == Decimal("0.0000")


def test_apply_quality_decision_returns_none_without_quant(quality_setup) -> None:
    tenant, _internal, rebut, variant_id, _quant = quality_setup
    with use_tenant(tenant.id):
        lot = StkLot.objects.create(tenant=tenant, variant_id=variant_id, name="LOT-NOQUANT")
        quality_state = set_quality_state(tenant=tenant, lot=lot, state=StkQualityState.STATE_REBUT)
        move = apply_quality_decision(quality_state, quarantine_or_scrap_location=rebut)
        assert move is None
