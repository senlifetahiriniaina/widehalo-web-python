"""RG-STK-1 (double entree) : cycle de vie `StkMove` (creation/validation/
annulation/extourne) et effet sur `StkQuant`, cas fixes (le test de
propriete Hypothesis complementaire est dans
`test_hypothesis_properties.py`)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLocation, StkMove, StkQuant
from apps.stocks.services.moves import cancel_move, create_move, reverse_move, validate_move
from apps.stocks.services.quants import available_qty, get_quant, on_hand_qty
from apps.stocks.services.warehouses import create_location, create_warehouse

pytestmark = pytest.mark.django_db


@pytest.fixture
def moves_setup():
    tenant = Tenant.objects.create(code="STK-MV-T", name="Stocks Moves Tenant")
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-01", name="Entrepot principal")
        internal = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="A1",
            name="Rayon A1",
            type=StkLocation.TYPE_INTERNE,
        )
        internal_2 = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="A2",
            name="Rayon A2",
            type=StkLocation.TYPE_INTERNE,
        )
        supplier = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="FRS",
            name="Fournisseur",
            type=StkLocation.TYPE_FOURNISSEUR,
        )
        client = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="CLI",
            name="Client",
            type=StkLocation.TYPE_CLIENT,
        )
        return tenant, warehouse, internal, internal_2, supplier, client


def test_create_move_refuses_non_positive_qty(moves_setup) -> None:
    tenant, _wh, internal, _i2, supplier, _client = moves_setup
    with use_tenant(tenant.id):
        with pytest.raises(ValidationError):
            create_move(
                tenant=tenant,
                variant_id=uuid.uuid4(),
                qty=Decimal(0),
                uom="pc",
                location_from=supplier,
                location_to=internal,
                date=dt.date(2026, 1, 1),
                move_type=StkMove.TYPE_RECEPTION,
            )
        with pytest.raises(ValidationError):
            create_move(
                tenant=tenant,
                variant_id=uuid.uuid4(),
                qty=Decimal("-5"),
                uom="pc",
                location_from=supplier,
                location_to=internal,
                date=dt.date(2026, 1, 1),
                move_type=StkMove.TYPE_RECEPTION,
            )


def test_create_move_refuses_same_from_and_to(moves_setup) -> None:
    tenant, _wh, internal, _i2, _supplier, _client = moves_setup
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        create_move(
            tenant=tenant,
            variant_id=uuid.uuid4(),
            qty=Decimal(10),
            uom="pc",
            location_from=internal,
            location_to=internal,
            date=dt.date(2026, 1, 1),
            move_type=StkMove.TYPE_TRANSFERT_INTERNE,
        )


def test_create_move_starts_draft(moves_setup) -> None:
    tenant, _wh, internal, _i2, supplier, _client = moves_setup
    with use_tenant(tenant.id):
        move = create_move(
            tenant=tenant,
            variant_id=uuid.uuid4(),
            qty=Decimal(10),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 1, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost_mga=Decimal("1000"),
        )
        assert move.state == StkMove.STATE_DRAFT
        assert move.reference
        assert move.value_mga == Decimal("10000.0000")


def test_validate_reception_updates_quants_both_sides(moves_setup) -> None:
    tenant, _wh, internal, _i2, supplier, _client = moves_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        move = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(10),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 1, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost_mga=Decimal("1000"),
        )
        validate_move(move)
        move.refresh_from_db()
        assert move.state == StkMove.STATE_DONE

        dest_quant = get_quant(variant_id, internal)
        assert dest_quant is not None
        assert dest_quant.qty == Decimal(10)
        assert dest_quant.unit_cost_mga == Decimal("1000.0000")
        assert dest_quant.value_mga == Decimal("10000.0000")

        # Emplacement virtuel fournisseur : quant negatif materialise
        # symetriquement (cf. docstring StkQuant), pas une anomalie.
        source_quant = get_quant(variant_id, supplier)
        assert source_quant is not None
        assert source_quant.qty == Decimal(-10)

        assert on_hand_qty(variant_id) == Decimal(10)


def test_validate_livraison_decrements_internal_increments_virtual_client(moves_setup) -> None:
    tenant, _wh, internal, _i2, supplier, client = moves_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        reception = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(10),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 1, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost_mga=Decimal("1000"),
        )
        validate_move(reception)

        livraison = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(4),
            uom="pc",
            location_from=internal,
            location_to=client,
            date=dt.date(2026, 1, 2),
            move_type=StkMove.TYPE_LIVRAISON,
        )
        validate_move(livraison)

        internal_quant = get_quant(variant_id, internal)
        assert internal_quant is not None
        assert internal_quant.qty == Decimal(6)

        client_quant = get_quant(variant_id, client)
        assert client_quant is not None
        assert client_quant.qty == Decimal(4)

        assert on_hand_qty(variant_id) == Decimal(6)
        assert available_qty(variant_id) == Decimal(6)


def test_validate_transfert_interne_moves_qty_without_valuation_effect(moves_setup) -> None:
    tenant, _wh, internal, internal_2, supplier, _client = moves_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        reception = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(10),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 1, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost_mga=Decimal("1000"),
        )
        validate_move(reception)

        transfer = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(3),
            uom="pc",
            location_from=internal,
            location_to=internal_2,
            date=dt.date(2026, 1, 2),
            move_type=StkMove.TYPE_TRANSFERT_INTERNE,
        )
        validate_move(transfer)

        assert transfer.valuation_layers.count() == 0
        assert get_quant(variant_id, internal).qty == Decimal(7)
        assert get_quant(variant_id, internal_2).qty == Decimal(3)
        assert on_hand_qty(variant_id) == Decimal(10)


def test_validate_move_refuses_when_not_draft(moves_setup) -> None:
    tenant, _wh, internal, _i2, supplier, _client = moves_setup
    with use_tenant(tenant.id):
        move = create_move(
            tenant=tenant,
            variant_id=uuid.uuid4(),
            qty=Decimal(10),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 1, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost_mga=Decimal("1000"),
        )
        validate_move(move)
        with pytest.raises(ValidationError):
            validate_move(move)


def test_cancel_move_requires_reason_and_only_draft(moves_setup) -> None:
    tenant, _wh, internal, _i2, supplier, _client = moves_setup
    with use_tenant(tenant.id):
        move = create_move(
            tenant=tenant,
            variant_id=uuid.uuid4(),
            qty=Decimal(10),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 1, 1),
            move_type=StkMove.TYPE_RECEPTION,
        )
        with pytest.raises(ValidationError):
            cancel_move(move, reason="")
        cancelled = cancel_move(move, reason="Erreur de saisie")
        assert cancelled.state == StkMove.STATE_CANCELLED

        done_move = create_move(
            tenant=tenant,
            variant_id=uuid.uuid4(),
            qty=Decimal(5),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 1, 1),
            move_type=StkMove.TYPE_RECEPTION,
        )
        validate_move(done_move)
        with pytest.raises(ValidationError):
            cancel_move(done_move, reason="Trop tard")


def test_reverse_move_creates_swapped_move(moves_setup) -> None:
    tenant, _wh, internal, _i2, supplier, _client = moves_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        move = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(10),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 1, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost_mga=Decimal("1000"),
        )
        validate_move(move)

        reversal = reverse_move(move)

        assert reversal.location_from_id == internal.id
        assert reversal.location_to_id == supplier.id
        assert reversal.qty == move.qty
        assert reversal.reverses_id == move.id
        assert reversal.state == StkMove.STATE_DONE

        # Le mouvement original n'est jamais modifie.
        move.refresh_from_db()
        assert move.state == StkMove.STATE_DONE

        # Net apres extourne : quantite revenue a zero des deux cotes.
        assert on_hand_qty(variant_id) == Decimal(0)
        assert StkQuant.objects.get(variant_id=variant_id, location=supplier).qty == Decimal(0)


def test_reverse_move_refuses_non_done(moves_setup) -> None:
    tenant, _wh, internal, _i2, supplier, _client = moves_setup
    with use_tenant(tenant.id):
        move = create_move(
            tenant=tenant,
            variant_id=uuid.uuid4(),
            qty=Decimal(10),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 1, 1),
            move_type=StkMove.TYPE_RECEPTION,
        )
        with pytest.raises(ValidationError):
            reverse_move(move)


@pytest.mark.parametrize(
    "move_type",
    [StkMove.TYPE_VENTE_COMPTOIR, StkMove.TYPE_CASSE],
)
def test_create_and_validate_move_accepts_the_two_new_outflow_natures(
    moves_setup, move_type
) -> None:
    """Phase 3 §5.8 (sprint A1) : « vente au comptoir » et « casse »,
    2 des 3 natures manquantes pour couvrir les douze du cahier, sont des
    `move_type` reellement acceptes par le cycle de vie complet
    creation/validation (sortie de stock interne existant) — pas
    seulement des libelles ajoutes a `MOVE_TYPE_CHOICES` sans effet."""
    tenant, _wh, internal, _i2, supplier, client = moves_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        reception = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(10),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 1, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost_mga=Decimal("100"),
        )
        validate_move(reception)

        move = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(3),
            uom="pc",
            location_from=internal,
            location_to=client,
            date=dt.date(2026, 1, 2),
            move_type=move_type,
        )
        validated = validate_move(move)
        assert validated.state == StkMove.STATE_DONE
        assert validated.move_type == move_type
        assert get_quant(variant_id, internal).qty == Decimal("7.0000")


def test_create_and_validate_move_accepts_the_sous_produit_nature(moves_setup) -> None:
    """« Sous-produit », la 3e nature manquante — représente une ENTRÉE en
    stock (byproduct de production), symétrique à `TYPE_PRODUCTION_IN`."""
    tenant, _wh, internal, _i2, supplier, _client = moves_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        move = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(4),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 1, 1),
            move_type=StkMove.TYPE_SOUS_PRODUIT,
            unit_cost_mga=Decimal("50"),
        )
        validated = validate_move(move)
        assert validated.state == StkMove.STATE_DONE
        assert get_quant(variant_id, internal).qty == Decimal("4.0000")
