from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkInventory, StkLocation, StkMove, StkPicking
from apps.stocks.services.moves import create_move, validate_move
from apps.stocks.services.warehouses import create_location, create_warehouse
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def stocks_screens_setup():
    tenant = Tenant.objects.create(code="UI-STK", name="UI Stocks Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="ui-stk@example.com", password="Str0ngPassw0rd!23")
        warehouse = create_warehouse(tenant=tenant, code="WH-UI", name="Entrepot UI")
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
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, user, warehouse, supplier, internal


def test_stock_view_screen_renders(stocks_screens_setup) -> None:
    client, *_ = stocks_screens_setup
    response = client.get("/stocks/stock-view/")
    assert response.status_code == 200
    assert b"Vue stock" in response.content


def test_move_list_create_detail_validate_round_trip(stocks_screens_setup) -> None:
    client, tenant, user, warehouse, supplier, internal = stocks_screens_setup

    response = client.get("/stocks/moves/")
    assert response.status_code == 200

    response = client.post(
        "/stocks/moves/",
        {
            "variant_id": str(uuid.uuid4()),
            "qty": "10",
            "uom": "m",
            "location_from_id": str(supplier.id),
            "location_to_id": str(internal.id),
            "date": "2026-01-10",
            "move_type": "reception",
            "unit_cost_mga": "500",
        },
        follow=True,
    )
    assert response.status_code == 200

    with use_tenant(tenant.id):
        from apps.stocks.models import StkMove

        move = StkMove.objects.get(location_from=supplier, location_to=internal)
    assert move.state == "draft"

    response = client.get(f"/stocks/moves/{move.id}/")
    assert response.status_code == 200
    assert move.reference.encode() in response.content or b"brouillon" in response.content

    response = client.post(f"/stocks/moves/{move.id}/", {"action": "validate"}, follow=True)
    assert response.status_code == 200
    move.refresh_from_db()
    assert move.state == "done"


def test_picking_list_create_detail_add_line_ready_validate_round_trip(
    stocks_screens_setup,
) -> None:
    client, tenant, user, warehouse, supplier, internal = stocks_screens_setup

    response = client.get("/stocks/pickings/")
    assert response.status_code == 200

    response = client.post(
        "/stocks/pickings/",
        {
            "type": "entree",
            "location_from_id": str(supplier.id),
            "location_to_id": str(internal.id),
        },
        follow=True,
    )
    assert response.status_code == 200

    with use_tenant(tenant.id):
        picking = StkPicking.objects.get(location_from=supplier, location_to=internal)

    response = client.get(f"/stocks/pickings/{picking.id}/")
    assert response.status_code == 200

    response = client.post(
        f"/stocks/pickings/{picking.id}/",
        {"action": "add_line", "variant_id": str(uuid.uuid4()), "qty": "5", "uom": "m"},
        follow=True,
    )
    assert response.status_code == 200

    response = client.post(f"/stocks/pickings/{picking.id}/", {"action": "ready"}, follow=True)
    assert response.status_code == 200
    picking.refresh_from_db()
    assert picking.state == "ready"

    response = client.post(f"/stocks/pickings/{picking.id}/", {"action": "validate"}, follow=True)
    assert response.status_code == 200
    picking.refresh_from_db()
    assert picking.state == "done"


def test_inventory_list_create_detail_start_count_validate_round_trip(
    stocks_screens_setup,
) -> None:
    client, tenant, user, warehouse, supplier, internal = stocks_screens_setup

    response = client.post(
        "/stocks/inventories/",
        {"warehouse_id": str(warehouse.id), "date": "2026-01-15", "type": "ponctuel"},
        follow=True,
    )
    assert response.status_code == 200

    with use_tenant(tenant.id):
        inventory = StkInventory.objects.get(warehouse=warehouse)

    variant_id = uuid.uuid4()
    response = client.post(
        f"/stocks/inventories/{inventory.id}/",
        {"action": "add_line", "variant_id": str(variant_id), "location_id": str(internal.id)},
        follow=True,
    )
    assert response.status_code == 200

    response = client.post(f"/stocks/inventories/{inventory.id}/", {"action": "start"}, follow=True)
    assert response.status_code == 200
    inventory.refresh_from_db()
    assert inventory.state == "in_progress"

    with use_tenant(tenant.id):
        line = inventory.lines.first()
    response = client.post(
        f"/stocks/inventories/{inventory.id}/",
        {"action": "record_count", "line_id": str(line.id), "qty_counted": "0", "reason": ""},
        follow=True,
    )
    assert response.status_code == 200

    response = client.post(
        f"/stocks/inventories/{inventory.id}/", {"action": "validate"}, follow=True
    )
    assert response.status_code == 200
    inventory.refresh_from_db()
    assert inventory.state == "validated"


def test_inventory_hides_theoretical_qty_until_validated(stocks_screens_setup) -> None:
    """STK-6 (Phase 3 §13, sprint A4) : la quantité théorique n'apparaît
    dans le HTML rendu qu'une fois l'inventaire "validated" — ni pendant
    la saisie, ni juste après avoir compté (avant validation du document
    complet)."""
    client, tenant, user, warehouse, supplier, internal = stocks_screens_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        move = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal("42"),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 1, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost_mga=Decimal("100"),
        )
        validate_move(move)

    client.post(
        "/stocks/inventories/",
        {"warehouse_id": str(warehouse.id), "date": "2026-01-15", "type": "ponctuel"},
        follow=True,
    )
    with use_tenant(tenant.id):
        inventory = StkInventory.objects.get(warehouse=warehouse)
    client.post(
        f"/stocks/inventories/{inventory.id}/",
        {"action": "add_line", "variant_id": str(variant_id), "location_id": str(internal.id)},
        follow=True,
    )
    client.post(f"/stocks/inventories/{inventory.id}/", {"action": "start"}, follow=True)

    response = client.get(f"/stocks/inventories/{inventory.id}/")
    assert b"42.0000" not in response.content

    with use_tenant(tenant.id):
        line = inventory.lines.first()
    client.post(
        f"/stocks/inventories/{inventory.id}/",
        {"action": "record_count", "line_id": str(line.id), "qty_counted": "42", "reason": ""},
        follow=True,
    )
    response = client.get(f"/stocks/inventories/{inventory.id}/")
    assert b"42.0000" not in response.content

    client.post(f"/stocks/inventories/{inventory.id}/", {"action": "validate"}, follow=True)
    response = client.get(f"/stocks/inventories/{inventory.id}/")
    assert b"42.0000" in response.content


def test_traceability_lookup_screen_renders(stocks_screens_setup) -> None:
    client, *_ = stocks_screens_setup
    response = client.get("/stocks/traceability/?lot_name=LOT-INEXISTANT")
    assert response.status_code == 200
    assert b"Aucun lot trouve" in response.content


def test_config_warehouses_screen_renders_and_creates(stocks_screens_setup) -> None:
    client, tenant, user, warehouse, supplier, internal = stocks_screens_setup
    response = client.get("/stocks/config/warehouses/")
    assert response.status_code == 200
    assert warehouse.code.encode() in response.content

    response = client.post(
        "/stocks/config/warehouses/",
        {"action": "create_warehouse", "code": "WH-NEW", "name": "Nouvel entrepot"},
        follow=True,
    )
    assert response.status_code == 200
    assert b"WH-NEW" in response.content


def test_reports_index_screen_renders(stocks_screens_setup) -> None:
    client, *_ = stocks_screens_setup
    response = client.get("/stocks/reports/")
    assert response.status_code == 200
    assert b"STK-ETAT" in response.content


def test_report_state_download_returns_json(stocks_screens_setup) -> None:
    client, *_ = stocks_screens_setup
    response = client.get("/stocks/reports/state/?format=json")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
