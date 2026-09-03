"""A1 refonte UX (Sprint 6 / L4, cf. docs/planning/2026-refonte-ux-sprints.md
§5) : saisie du lot + DLC/DLUO a la reception, suggestion FEFO a la
sortie. Meme idiome de connexion que tests/ui/test_stocks_screens.py."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLocation, StkLot, StkPicking
from apps.stocks.services.moves import validate_move
from apps.stocks.services.pickings import add_picking_line, create_picking
from apps.stocks.services.warehouses import create_location, create_warehouse
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def lot_dlc_setup():
    tenant = Tenant.objects.create(code="UI-LOT", name="UI Lot Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="ui-lot@example.com", password="Str0ngPassw0rd!23")
        warehouse = create_warehouse(tenant=tenant, code="WH-LOT", name="Entrepot lot")
        supplier = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="FRS",
            name="Fournisseur",
            type=StkLocation.TYPE_FOURNISSEUR,
        )
        internal = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="A1",
            name="Rayon A1",
            type=StkLocation.TYPE_INTERNE,
        )
        client_loc = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="CLI",
            name="Client",
            type=StkLocation.TYPE_CLIENT,
        )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, user, warehouse, supplier, internal, client_loc


def test_reception_add_line_creates_lot_with_dlc(lot_dlc_setup) -> None:
    client, tenant, _user, _wh, supplier, internal, _cli = lot_dlc_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        picking = create_picking(
            tenant=tenant, type=StkPicking.TYPE_ENTREE, location_from=supplier, location_to=internal
        )

    response = client.post(
        f"/stocks/pickings/{picking.id}/",
        {
            "action": "add_line",
            "variant_id": str(variant_id),
            "qty": "10",
            "uom": "pc",
            "lot_name": "LOT-2026-001",
            "date_production": "2026-08-01",
            "date_expiry": "2026-09-15",
            "supplier_lot": "FOURN-LOT-9",
        },
    )
    assert response.status_code == 302

    with use_tenant(tenant.id):
        lot = StkLot.objects.get(tenant=tenant, variant_id=variant_id, name="LOT-2026-001")
        assert str(lot.date_expiry) == "2026-09-15"
        assert lot.supplier_lot == "FOURN-LOT-9"
        move = picking.moves.get()
        assert move.lot_id == lot.id


def test_reception_add_line_without_lot_name_leaves_lot_empty(lot_dlc_setup) -> None:
    client, tenant, _user, _wh, supplier, internal, _cli = lot_dlc_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        picking = create_picking(
            tenant=tenant, type=StkPicking.TYPE_ENTREE, location_from=supplier, location_to=internal
        )

    client.post(
        f"/stocks/pickings/{picking.id}/",
        {"action": "add_line", "variant_id": str(variant_id), "qty": "5", "uom": "pc"},
    )

    with use_tenant(tenant.id):
        move = picking.moves.get()
        assert move.lot_id is None


def test_fefo_suggestion_endpoint_suggests_lot_closest_to_expiry(lot_dlc_setup) -> None:
    client, tenant, _user, _wh, supplier, internal, client_loc = lot_dlc_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        lot_far = StkLot.objects.create(
            tenant=tenant, variant_id=variant_id, name="LOT-FAR", date_expiry="2027-01-01"
        )
        lot_near = StkLot.objects.create(
            tenant=tenant, variant_id=variant_id, name="LOT-NEAR", date_expiry="2026-06-01"
        )
        reception = create_picking(
            tenant=tenant, type=StkPicking.TYPE_ENTREE, location_from=supplier, location_to=internal
        )
        for lot in (lot_far, lot_near):
            move = add_picking_line(
                reception, variant_id=variant_id, qty=Decimal(10), uom="pc", lot=lot
            )
            validate_move(move)

        outbound = create_picking(
            tenant=tenant,
            type=StkPicking.TYPE_SORTIE,
            location_from=internal,
            location_to=client_loc,
        )

    response = client.get(
        f"/stocks/pickings/{outbound.id}/fefo-suggestion/",
        # 15 > la disponibilite du seul lot le plus proche de peremption (10) :
        # force l'allocation a deborder sur le second lot, pour verifier
        # l'ordre de priorite (pas seulement la presence d'un lot).
        {"variant_id": str(variant_id), "qty": "15"},
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "LOT-NEAR" in body
    assert "LOT-FAR" in body
    assert body.index("LOT-NEAR") < body.index("LOT-FAR")


def test_fefo_suggestion_endpoint_without_variant_shows_hint() -> None:
    tenant = Tenant.objects.create(code="UI-LOT-2", name="UI Lot Tenant 2")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="ui-lot2@example.com", password="Str0ngPassw0rd!23")
        warehouse = create_warehouse(tenant=tenant, code="WH-LOT2", name="Entrepot lot 2")
        supplier = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="FRS2",
            name="Fournisseur",
            type=StkLocation.TYPE_FOURNISSEUR,
        )
        internal = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="A2",
            name="Rayon A2",
            type=StkLocation.TYPE_INTERNE,
        )
        picking = create_picking(
            tenant=tenant, type=StkPicking.TYPE_SORTIE, location_from=internal, location_to=supplier
        )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get(f"/stocks/pickings/{picking.id}/fefo-suggestion/")
    assert response.status_code == 200
    assert "Aucune suggestion" in response.content.decode()
