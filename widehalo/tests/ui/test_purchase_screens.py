from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from apps.catalog.models import ProductTemplate, ProductVariant, UnitOfMeasure
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.purchase.services.orders import create_order
from apps.purchase.services.requisitions import add_requisition_line, create_requisition
from apps.purchase.services.rfq import add_rfq_line, create_rfq
from apps.stocks.models import StkLocation, StkWarehouse
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def purchase_screens_setup():
    tenant = Tenant.objects.create(code="UI-PUR", name="UI Purchase Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="ui-pur@example.com", password="Str0ngPassw0rd!23")
        # `add_requisition_line` resout `estimated_price_mga` via
        # `catalog.services.public.get_variant_price`, qui exige un
        # `ProductVariant` REEL (pas un simple UUID opaque) — meme helper
        # que `apps/purchase/tests/test_reordering.py::_make_variant`.
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PC-UI", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )
        template = ProductTemplate.objects.create(
            tenant=tenant,
            name="Tissu coton",
            base_uom=uom,
            reference="TPL-UI-PUR",
            base_price_mga=Decimal("1000"),
        )
        variant = ProductVariant.objects.create(
            tenant=tenant, template=template, reference="VAR-UI-PUR"
        )
        requisition = create_requisition(tenant=tenant, requester=user, date_needed=dt.date.today())
        add_requisition_line(
            requisition, variant_id=variant.id, description="Tissu coton", qty=Decimal(10)
        )
        rfq = create_rfq(tenant=tenant, date=dt.date.today())
        add_rfq_line(rfq, variant_id=uuid.uuid4(), description="Tissu coton", qty=Decimal(10))
        # P2 (Phase 3 §12.1) : `warehouse_id` est une precondition REELLE
        # de la reception depuis que `receive_order_line` cree un vrai
        # `StkMove` (`apps.purchase.services.receiving`) — meme patron
        # que `apps/purchase/tests/test_receiving.py::receiving_setup`.
        warehouse = StkWarehouse.objects.create(tenant=tenant, code="WH-UI-PUR", name="Entrepôt")
        StkLocation.objects.create(
            tenant=tenant,
            warehouse=warehouse,
            code="A1-UI-PUR",
            name="Rayon",
            type=StkLocation.TYPE_INTERNE,
        )
        order = create_order(
            tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today(), warehouse_id=warehouse.id
        )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, user, requisition, rfq, order


def test_requisition_list_screen_renders(purchase_screens_setup) -> None:
    client, *_ = purchase_screens_setup
    response = client.get("/purchase/")
    assert response.status_code == 200


def test_requisition_create_screen(purchase_screens_setup) -> None:
    client, *_ = purchase_screens_setup
    response = client.post("/purchase/requisitions/new/", {"date_needed": str(dt.date.today())})
    assert response.status_code == 302


def test_requisition_detail_submit_approve_and_create_order_flow(purchase_screens_setup) -> None:
    client, tenant, _user, requisition, _rfq, _order = purchase_screens_setup

    response = client.post(f"/purchase/requisitions/{requisition.id}/", {"action": "submit"})
    assert response.status_code == 302

    detail = client.get(f"/purchase/requisitions/{requisition.id}/")
    assert b"Soumise" in detail.content

    response = client.post(f"/purchase/requisitions/{requisition.id}/", {"action": "approve"})
    assert response.status_code == 302

    response = client.post(
        f"/purchase/requisitions/{requisition.id}/",
        {"action": "create_order", "partner_id": str(uuid.uuid4())},
    )
    assert response.status_code == 302
    assert response.url.startswith("/purchase/orders/")

    with use_tenant(tenant.id):
        requisition.refresh_from_db()
        assert requisition.orders.count() == 1


def test_requisition_detail_reject_requires_reason(purchase_screens_setup) -> None:
    client, tenant, _user, requisition, _rfq, _order = purchase_screens_setup
    client.post(f"/purchase/requisitions/{requisition.id}/", {"action": "submit"})

    response = client.post(
        f"/purchase/requisitions/{requisition.id}/", {"action": "reject", "reason": ""}
    )
    assert response.status_code == 200
    assert b"motif" in response.content.lower() or b"error" in response.content.lower()

    response = client.post(
        f"/purchase/requisitions/{requisition.id}/",
        {"action": "reject", "reason": "Budget insuffisant"},
    )
    assert response.status_code == 302
    with use_tenant(tenant.id):
        requisition.refresh_from_db()
        assert requisition.state == "rejected"


def test_rfq_list_screen_renders(purchase_screens_setup) -> None:
    client, *_ = purchase_screens_setup
    response = client.get("/purchase/rfqs/")
    assert response.status_code == 200


def test_rfq_create_screen(purchase_screens_setup) -> None:
    client, *_ = purchase_screens_setup
    response = client.post("/purchase/rfqs/new/", {"date": str(dt.date.today())})
    assert response.status_code == 302


def test_rfq_detail_full_flow_to_award(purchase_screens_setup) -> None:
    client, tenant, _user, _requisition, rfq, _order = purchase_screens_setup

    response = client.post(
        f"/purchase/rfqs/{rfq.id}/", {"action": "add_supplier", "partner_id": str(uuid.uuid4())}
    )
    assert response.status_code == 302

    response = client.post(f"/purchase/rfqs/{rfq.id}/", {"action": "send"})
    assert response.status_code == 302

    with use_tenant(tenant.id):
        rfq.refresh_from_db()
        variant_id = rfq.lines.first().variant_id

    response = client.post(
        f"/purchase/rfqs/{rfq.id}/",
        {
            "action": "record_response",
            "resp_partner_id": str(uuid.uuid4()),
            "resp_date_received": str(dt.date.today()),
            "resp_variant_id": str(variant_id),
            "resp_qty": "10",
            "resp_unit_price_mga": "5000",
            "resp_lead_time_days": "7",
        },
    )
    assert response.status_code == 302

    with use_tenant(tenant.id):
        rfq.refresh_from_db()
        response_id = rfq.responses.first().id

    detail = client.get(f"/purchase/rfqs/{rfq.id}/")
    assert b"5000" in detail.content or b"5000.0000" in detail.content

    response = client.post(
        f"/purchase/rfqs/{rfq.id}/", {"action": "award", "response_id": str(response_id)}
    )
    assert response.status_code == 302
    assert response.url.startswith("/purchase/orders/")


def test_order_list_screen_renders_and_filters_by_state(purchase_screens_setup) -> None:
    client, *_ = purchase_screens_setup
    response = client.get("/purchase/orders/")
    assert response.status_code == 200
    response = client.get("/purchase/orders/?state=draft")
    assert response.status_code == 200


def test_order_create_screen(purchase_screens_setup) -> None:
    client, *_ = purchase_screens_setup
    response = client.post(
        "/purchase/orders/new/", {"partner_id": str(uuid.uuid4()), "date": str(dt.date.today())}
    )
    assert response.status_code == 302


def test_order_detail_full_fsm_workflow_no_full_reload_uses_redirect(
    purchase_screens_setup,
) -> None:
    """Chaque action de bandeau de workflow repond par une redirection
    (302) vers la meme fiche detail — jamais un re-rendu de page complete
    depuis un formulaire d'action, meme convention que
    `tests/ui/test_sales_screens.py`."""
    client, tenant, _user, _requisition, _rfq, order = purchase_screens_setup

    with use_tenant(tenant.id):
        from apps.purchase.services.orders import add_order_line

        add_order_line(
            order,
            variant_id=uuid.uuid4(),
            description="Tissu coton",
            qty=Decimal(10),
            unit_price_mga=Decimal(5000),
        )
        line_id = order.lines.first().id

    for action in ("submit", "validate", "send", "confirm", "in_transit"):
        response = client.post(f"/purchase/orders/{order.id}/", {"action": action})
        assert response.status_code == 302

    detail = client.get(f"/purchase/orders/{order.id}/")
    assert b"En transit" in detail.content

    response = client.post(
        f"/purchase/orders/{order.id}/",
        {
            "action": "receive_line",
            "line_id": str(line_id),
            "qty_received_now": "10",
            "quality_status": "conforme",
        },
    )
    assert response.status_code == 302

    with use_tenant(tenant.id):
        order.refresh_from_db()
        assert order.state == "received"

    response = client.post(
        f"/purchase/orders/{order.id}/",
        {
            "action": "record_invoice",
            "invoice_line_id": str(line_id),
            "invoice_qty": "10",
            "invoice_unit_price_mga": "5000",
            "invoice_date": str(dt.date.today()),
        },
    )
    assert response.status_code == 302


def test_order_detail_cancel_requires_reason(purchase_screens_setup) -> None:
    client, tenant, _user, _requisition, _rfq, order = purchase_screens_setup
    response = client.post(f"/purchase/orders/{order.id}/", {"action": "cancel", "reason": ""})
    assert response.status_code == 200
    assert b"motif" in response.content.lower() or b"error" in response.content.lower()

    response = client.post(
        f"/purchase/orders/{order.id}/", {"action": "cancel", "reason": "Fournisseur indisponible"}
    )
    assert response.status_code == 302
    with use_tenant(tenant.id):
        order.refresh_from_db()
        assert order.state == "cancelled"


def test_cra_list_screen_create_submit_validate_flow(purchase_screens_setup) -> None:
    client, tenant, _user, _requisition, _rfq, order = purchase_screens_setup

    response = client.get("/purchase/cra/")
    assert response.status_code == 200

    response = client.post(
        "/purchase/cra/",
        {
            "action": "create",
            "date": str(dt.date.today()),
            "partner_id": str(uuid.uuid4()),
            "activity_type": "sourcing",
            "hours": "4",
            "order_id": str(order.id),
        },
    )
    assert response.status_code == 302

    with use_tenant(tenant.id):
        from apps.purchase.models import PurCra

        cra = PurCra.objects.get(order=order)

    response = client.post("/purchase/cra/", {"action": "submit", "cra_id": str(cra.id)})
    assert response.status_code == 302

    response = client.post("/purchase/cra/", {"action": "validate", "cra_id": str(cra.id)})
    assert response.status_code == 302

    with use_tenant(tenant.id):
        cra.refresh_from_db()
        assert cra.state == "validated"


def test_cri_list_screen_create_and_close_flow(purchase_screens_setup) -> None:
    client, tenant, _user, _requisition, _rfq, order = purchase_screens_setup

    response = client.get("/purchase/cri/")
    assert response.status_code == 200

    response = client.post(
        "/purchase/cri/",
        {
            "action": "create",
            "date": str(dt.date.today()),
            "type": "retard",
            "partner_id": str(uuid.uuid4()),
            "order_id": str(order.id),
            "description": "Livraison en retard",
        },
    )
    assert response.status_code == 302

    with use_tenant(tenant.id):
        from apps.purchase.models import PurCri

        cri = PurCri.objects.get(order=order)

    response = client.post("/purchase/cri/", {"action": "close", "cri_id": str(cri.id)})
    assert response.status_code == 302
    with use_tenant(tenant.id):
        cri.refresh_from_db()
        assert cri.state == "closed"
