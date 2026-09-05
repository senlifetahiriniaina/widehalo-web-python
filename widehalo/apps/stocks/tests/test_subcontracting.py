"""Bloc C, C2 (RG-MRP-8, PRD-9) : envoi/réception de matière chez un
sous-traitant en deux phases (`stocks.services.public.
send_to_subcontractor`/`receive_from_subcontractor`), miroir du patron
`transfer_between_warehouses`/`receive_warehouse_transfer` déjà testé
dans `test_moves.py`."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLocation, StkMove, StkValuationLayer
from apps.stocks.services.moves import create_move, validate_move
from apps.stocks.services.public import receive_from_subcontractor, send_to_subcontractor
from apps.stocks.services.quants import get_quant, on_hand_qty
from apps.stocks.services.warehouses import create_location, create_warehouse

pytestmark = pytest.mark.django_db


@pytest.fixture
def subcontracting_setup():
    tenant = Tenant.objects.create(code="STK-SUB-T", name="Stocks Subcontracting Tenant")
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-SUB", name="Entrepot")
        internal = create_location(tenant=tenant, warehouse=warehouse, code="A1", name="Rayon A1")
        rebut = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="REB",
            name="Rebut",
            type=StkLocation.TYPE_REBUT,
        )
        supplier = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="FRS",
            name="Fournisseur",
            type=StkLocation.TYPE_FOURNISSEUR,
        )
        variant_id = uuid.uuid4()
        # Stock initial reel (RG-STK-10 refuse un envoi qui ferait passer
        # le quant interne sous zero) — recu au meme cout unitaire que
        # l'envoi, pour que la conservation de valeur soit exacte.
        reception = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(10),
            uom="pcs",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 1, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost_mga=Decimal(1000),
        )
        validate_move(reception)

        move_id = send_to_subcontractor(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(10),
            uom="pcs",
            warehouse_id=warehouse.id,
            date=dt.date(2026, 1, 5),
            unit_cost_mga=Decimal(1000),
        )
        return tenant, warehouse, internal, rebut, variant_id, move_id


def test_send_to_subcontractor_moves_qty_without_consuming_valuation(subcontracting_setup) -> None:
    """PRD-9 : le mouvement d'envoi (interne -> sous-traitant) ne doit
    consommer AUCUNE couche de valorisation — la matière reste dans le
    périmètre "interne au sens valorisation" (`_is_valuation_internal`
    étendu)."""
    tenant, warehouse, internal, _rebut, variant_id, move_id = subcontracting_setup
    with use_tenant(tenant.id):
        move = StkMove.objects.get(id=move_id)
        assert move.state == StkMove.STATE_DONE
        assert move.move_type == StkMove.TYPE_TRANSFERT_INTERNE

        subcontractor_location = StkLocation.objects.get(
            tenant=tenant, warehouse=warehouse, type=StkLocation.TYPE_SOUS_TRAITANT
        )
        quant = get_quant(variant_id, subcontractor_location)
        assert quant is not None
        assert quant.qty == Decimal(10)

        # Deux couches actives (source interne vidée, sous-traitant créée)
        # totalisant toujours la valeur d'origine — rien n'a été
        # "sorti" du périmètre de valorisation.
        layers = StkValuationLayer.objects.filter(tenant=tenant, variant_id=variant_id)
        total_remaining_value = sum((layer.remaining_value_mga for layer in layers), Decimal(0))
        assert total_remaining_value == Decimal(10) * Decimal(1000)


def test_receive_from_subcontractor_partial_leaves_balance(subcontracting_setup) -> None:
    tenant, warehouse, internal, _rebut, variant_id, move_id = subcontracting_setup
    with use_tenant(tenant.id):
        result = receive_from_subcontractor(
            tenant=tenant, send_move_id=move_id, date=dt.date(2026, 1, 20), qty_received=Decimal(6)
        )
        assert result["received_move_id"] is not None
        assert result["rejected_move_id"] is None

        assert on_hand_qty(variant_id, location=internal) == Decimal(6)

        subcontractor_location = StkLocation.objects.get(
            tenant=tenant, warehouse=warehouse, type=StkLocation.TYPE_SOUS_TRAITANT
        )
        quant = get_quant(variant_id, subcontractor_location)
        assert quant is not None
        assert quant.qty == Decimal(4)  # solde reste chez le sous-traitant


def test_receive_from_subcontractor_rejected_qty_goes_to_rebut(subcontracting_setup) -> None:
    tenant, warehouse, internal, rebut, variant_id, move_id = subcontracting_setup
    with use_tenant(tenant.id):
        result = receive_from_subcontractor(
            tenant=tenant,
            send_move_id=move_id,
            date=dt.date(2026, 1, 20),
            qty_received=Decimal(7),
            qty_rejected=Decimal(3),
            rebut_location_id=rebut.id,
        )
        assert result["received_move_id"] is not None
        assert result["rejected_move_id"] is not None

        assert on_hand_qty(variant_id, location=internal) == Decimal(7)
        assert on_hand_qty(variant_id, location=rebut) == Decimal(3)

        subcontractor_location = StkLocation.objects.get(
            tenant=tenant, warehouse=warehouse, type=StkLocation.TYPE_SOUS_TRAITANT
        )
        quant = get_quant(variant_id, subcontractor_location)
        assert quant is not None
        assert quant.qty == Decimal(0)


def test_receive_from_subcontractor_refuses_qty_above_available(subcontracting_setup) -> None:
    tenant, _warehouse, _internal, _rebut, _variant_id, move_id = subcontracting_setup
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        receive_from_subcontractor(
            tenant=tenant,
            send_move_id=move_id,
            date=dt.date(2026, 1, 20),
            qty_received=Decimal(11),
        )


def test_receive_from_subcontractor_requires_rebut_location_for_rejected_qty(
    subcontracting_setup,
) -> None:
    tenant, _warehouse, _internal, _rebut, _variant_id, move_id = subcontracting_setup
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        receive_from_subcontractor(
            tenant=tenant,
            send_move_id=move_id,
            date=dt.date(2026, 1, 20),
            qty_received=Decimal(5),
            qty_rejected=Decimal(2),
        )
