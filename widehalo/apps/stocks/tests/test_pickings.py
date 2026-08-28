"""ST4 (§5.8, `StkPicking`) : creation d'un picking pour chacun des 3
types, ajout de lignes (mapping `move_type` par defaut + override
explicite), gates du workflow lineaire `draft/waiting -> ready -> done`
(+ `cancelled`)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLocation, StkMove, StkPicking
from apps.stocks.services.pickings import (
    add_picking_line,
    cancel_picking,
    create_picking,
    mark_picking_ready,
    validate_picking,
)
from apps.stocks.services.quants import on_hand_qty
from apps.stocks.services.warehouses import create_location, create_warehouse

pytestmark = pytest.mark.django_db


@pytest.fixture
def pickings_setup():
    tenant = Tenant.objects.create(code="STK-PCK-T", name="Stocks Pickings Tenant")
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


def test_create_picking_each_type(pickings_setup) -> None:
    tenant, _wh, internal, internal_2, supplier, client = pickings_setup
    with use_tenant(tenant.id):
        reception = create_picking(
            tenant=tenant,
            type=StkPicking.TYPE_ENTREE,
            location_from=supplier,
            location_to=internal,
        )
        expedition = create_picking(
            tenant=tenant,
            type=StkPicking.TYPE_SORTIE,
            location_from=internal,
            location_to=client,
        )
        transfert = create_picking(
            tenant=tenant,
            type=StkPicking.TYPE_INTERNE,
            location_from=internal,
            location_to=internal_2,
        )
        for picking, expected_type in (
            (reception, StkPicking.TYPE_ENTREE),
            (expedition, StkPicking.TYPE_SORTIE),
            (transfert, StkPicking.TYPE_INTERNE),
        ):
            assert picking.state == StkPicking.STATE_DRAFT
            assert picking.reference
            assert picking.type == expected_type


def test_add_picking_line_resolves_default_move_type(pickings_setup) -> None:
    tenant, _wh, internal, internal_2, supplier, client = pickings_setup
    with use_tenant(tenant.id):
        reception = create_picking(
            tenant=tenant,
            type=StkPicking.TYPE_ENTREE,
            location_from=supplier,
            location_to=internal,
        )
        move = add_picking_line(reception, variant_id=uuid.uuid4(), qty=Decimal(10), uom="pc")
        assert move.move_type == StkMove.TYPE_RECEPTION
        assert move.picking_id == reception.id
        assert move.location_from_id == supplier.id
        assert move.location_to_id == internal.id

        expedition = create_picking(
            tenant=tenant, type=StkPicking.TYPE_SORTIE, location_from=internal, location_to=client
        )
        move = add_picking_line(expedition, variant_id=uuid.uuid4(), qty=Decimal(5), uom="pc")
        assert move.move_type == StkMove.TYPE_LIVRAISON

        transfert = create_picking(
            tenant=tenant,
            type=StkPicking.TYPE_INTERNE,
            location_from=internal,
            location_to=internal_2,
        )
        move = add_picking_line(transfert, variant_id=uuid.uuid4(), qty=Decimal(3), uom="pc")
        assert move.move_type == StkMove.TYPE_TRANSFERT_INTERNE


def test_add_picking_line_explicit_move_type_override(pickings_setup) -> None:
    tenant, _wh, internal, _i2, _supplier, client = pickings_setup
    with use_tenant(tenant.id):
        expedition = create_picking(
            tenant=tenant, type=StkPicking.TYPE_SORTIE, location_from=internal, location_to=client
        )
        move = add_picking_line(
            expedition,
            variant_id=uuid.uuid4(),
            qty=Decimal(2),
            uom="pc",
            move_type=StkMove.TYPE_RETOUR,
        )
        assert move.move_type == StkMove.TYPE_RETOUR


def test_add_picking_line_refuses_after_ready(pickings_setup) -> None:
    tenant, _wh, internal, _i2, supplier, _client = pickings_setup
    with use_tenant(tenant.id):
        picking = create_picking(
            tenant=tenant, type=StkPicking.TYPE_ENTREE, location_from=supplier, location_to=internal
        )
        add_picking_line(picking, variant_id=uuid.uuid4(), qty=Decimal(1), uom="pc")
        mark_picking_ready(picking)
        with pytest.raises(ValidationError):
            add_picking_line(picking, variant_id=uuid.uuid4(), qty=Decimal(1), uom="pc")


def test_mark_picking_ready_refuses_with_zero_lines(pickings_setup) -> None:
    tenant, _wh, internal, _i2, supplier, _client = pickings_setup
    with use_tenant(tenant.id):
        picking = create_picking(
            tenant=tenant, type=StkPicking.TYPE_ENTREE, location_from=supplier, location_to=internal
        )
        with pytest.raises(ValidationError):
            mark_picking_ready(picking)


def test_validate_picking_validates_all_attached_moves(pickings_setup) -> None:
    tenant, _wh, internal, _i2, supplier, _client = pickings_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        picking = create_picking(
            tenant=tenant, type=StkPicking.TYPE_ENTREE, location_from=supplier, location_to=internal
        )
        add_picking_line(
            picking,
            variant_id=variant_id,
            qty=Decimal(10),
            uom="pc",
            unit_cost_mga=Decimal("1000"),
        )
        add_picking_line(
            picking,
            variant_id=variant_id,
            qty=Decimal(5),
            uom="pc",
            unit_cost_mga=Decimal("1000"),
        )
        mark_picking_ready(picking)
        validate_picking(picking, date_done=dt.date(2026, 3, 1))
        picking.refresh_from_db()
        assert picking.state == StkPicking.STATE_DONE
        assert picking.date_done == dt.date(2026, 3, 1)
        for move in picking.moves.all():
            assert move.state == StkMove.STATE_DONE
        assert on_hand_qty(variant_id, location=internal) == Decimal("15.0000")


def test_validate_picking_defaults_date_done_to_today(pickings_setup) -> None:
    tenant, _wh, internal, _i2, supplier, _client = pickings_setup
    with use_tenant(tenant.id):
        picking = create_picking(
            tenant=tenant, type=StkPicking.TYPE_ENTREE, location_from=supplier, location_to=internal
        )
        add_picking_line(picking, variant_id=uuid.uuid4(), qty=Decimal(1), uom="pc")
        mark_picking_ready(picking)
        validate_picking(picking)
        picking.refresh_from_db()
        assert picking.date_done == dt.date.today()


def test_validate_picking_refuses_non_ready(pickings_setup) -> None:
    tenant, _wh, internal, _i2, supplier, _client = pickings_setup
    with use_tenant(tenant.id):
        picking = create_picking(
            tenant=tenant, type=StkPicking.TYPE_ENTREE, location_from=supplier, location_to=internal
        )
        add_picking_line(picking, variant_id=uuid.uuid4(), qty=Decimal(1), uom="pc")
        with pytest.raises(ValidationError):
            validate_picking(picking)


def test_cancel_picking_requires_reason(pickings_setup) -> None:
    tenant, _wh, internal, _i2, supplier, _client = pickings_setup
    with use_tenant(tenant.id):
        picking = create_picking(
            tenant=tenant, type=StkPicking.TYPE_ENTREE, location_from=supplier, location_to=internal
        )
        with pytest.raises(ValidationError):
            cancel_picking(picking, reason="")


def test_cancel_picking_cancels_attached_draft_moves(pickings_setup) -> None:
    tenant, _wh, internal, _i2, supplier, _client = pickings_setup
    with use_tenant(tenant.id):
        picking = create_picking(
            tenant=tenant, type=StkPicking.TYPE_ENTREE, location_from=supplier, location_to=internal
        )
        move = add_picking_line(picking, variant_id=uuid.uuid4(), qty=Decimal(1), uom="pc")
        cancel_picking(picking, reason="Commande annulee")
        picking.refresh_from_db()
        move.refresh_from_db()
        assert picking.state == StkPicking.STATE_CANCELLED
        assert move.state == StkMove.STATE_CANCELLED
        assert move.cancel_reason == "Commande annulee"


def test_cancel_picking_refuses_done(pickings_setup) -> None:
    tenant, _wh, internal, _i2, supplier, _client = pickings_setup
    with use_tenant(tenant.id):
        picking = create_picking(
            tenant=tenant, type=StkPicking.TYPE_ENTREE, location_from=supplier, location_to=internal
        )
        add_picking_line(picking, variant_id=uuid.uuid4(), qty=Decimal(1), uom="pc")
        mark_picking_ready(picking)
        validate_picking(picking)
        with pytest.raises(ValidationError):
            cancel_picking(picking, reason="trop tard")
