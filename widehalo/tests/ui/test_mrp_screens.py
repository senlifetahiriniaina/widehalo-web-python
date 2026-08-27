from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.mrp.models import MrpWorkcenter, MrpWorkshop
from apps.mrp.services.bom import activate_bom, add_bom_line, create_bom
from apps.mrp.services.orders import create_order
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def mrp_screens_setup():
    tenant = Tenant.objects.create(code="UI-MRP", name="UI MRP Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="ui-mrp@example.com", password="Str0ngPassw0rd!23")
        workshop = MrpWorkshop.objects.create(tenant=tenant, code="ATL-UI", name="Atelier UI")
        bom = create_bom(tenant=tenant, code="BOM-UI", product_template_id=uuid.uuid4())
        add_bom_line(bom, component_template_id=uuid.uuid4(), qty=Decimal(1))
        activate_bom(bom)
        order = create_order(tenant=tenant, bom=bom, workshop=workshop, qty=Decimal(5))
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, user, workshop, bom, order


def test_order_create_screen(mrp_screens_setup) -> None:
    client, _tenant, _user, workshop, bom, _order = mrp_screens_setup
    response = client.post(
        "/mrp/new/", {"bom_id": str(bom.id), "workshop_id": str(workshop.id), "qty": "3"}
    )
    assert response.status_code == 302


def test_order_detail_confirm_transition(mrp_screens_setup) -> None:
    client, _tenant, _user, _workshop, _bom, order = mrp_screens_setup
    response = client.post(f"/mrp/{order.id}/", {"action": "confirm"})
    assert response.status_code == 302

    detail = client.get(f"/mrp/{order.id}/")
    assert b"Confirme" in detail.content


def test_order_list_screen_renders(mrp_screens_setup) -> None:
    client, _tenant, _user, _workshop, _bom, _order = mrp_screens_setup
    response = client.get("/mrp/")
    assert response.status_code == 200


def test_work_order_create_and_progress(mrp_screens_setup) -> None:
    client, tenant, _user, workshop, _bom, order = mrp_screens_setup
    with use_tenant(tenant.id):
        workcenter = MrpWorkcenter.objects.create(
            tenant=tenant, workshop=workshop, code="WC-UI", name="Poste UI", type="couture"
        )

    response = client.post(
        f"/mrp/{order.id}/",
        {
            "action": "create_work_order",
            "workcenter_id": str(workcenter.id),
            "wo_qty_planned": "5",
        },
    )
    assert response.status_code == 302

    with use_tenant(tenant.id):
        work_order = order.work_orders.get()

    response = client.post(
        f"/mrp/{order.id}/", {"action": "start_work_order", "work_order_id": str(work_order.id)}
    )
    assert response.status_code == 302

    response = client.post(
        f"/mrp/{order.id}/", {"action": "pause_work_order", "work_order_id": str(work_order.id)}
    )
    assert response.status_code == 302

    response = client.post(
        f"/mrp/{order.id}/", {"action": "start_work_order", "work_order_id": str(work_order.id)}
    )
    assert response.status_code == 302

    response = client.post(
        f"/mrp/{order.id}/",
        {
            "action": "done_work_order",
            "work_order_id": str(work_order.id),
            "wo_qty_done": "5",
        },
    )
    assert response.status_code == 302

    with use_tenant(tenant.id):
        work_order.refresh_from_db()
    assert work_order.state == "done"


def test_subcontract_send_and_receive(mrp_screens_setup) -> None:
    client, tenant, _user, _workshop, _bom, order = mrp_screens_setup
    response = client.post(
        f"/mrp/{order.id}/",
        {
            "action": "create_subcontract",
            "partner_id": str(uuid.uuid4()),
            "sub_qty": "10",
        },
    )
    assert response.status_code == 302

    with use_tenant(tenant.id):
        subcontract_order = order.subcontract_orders.get()

    response = client.post(
        f"/mrp/{order.id}/",
        {
            "action": "receive_subcontract",
            "subcontract_id": str(subcontract_order.id),
            "sub_qty_received": "10",
        },
    )
    assert response.status_code == 302

    with use_tenant(tenant.id):
        subcontract_order.refresh_from_db()
    assert subcontract_order.state == "received"


def test_cra_create_submit_validate(mrp_screens_setup) -> None:
    client, tenant, _user, workshop, _bom, order = mrp_screens_setup
    response = client.post(
        f"/mrp/{order.id}/",
        {
            "action": "create_cra",
            "cra_workshop_id": str(workshop.id),
            "cra_date": "2026-08-20",
            "cra_hours": "8",
        },
    )
    assert response.status_code == 302

    with use_tenant(tenant.id):
        cra = order.cra_entries.get()

    response = client.post(f"/mrp/{order.id}/", {"action": "submit_cra", "cra_id": str(cra.id)})
    assert response.status_code == 302

    response = client.post(f"/mrp/{order.id}/", {"action": "validate_cra", "cra_id": str(cra.id)})
    assert response.status_code == 302

    with use_tenant(tenant.id):
        cra.refresh_from_db()
    assert cra.state == "validated"


def test_cri_create(mrp_screens_setup) -> None:
    client, tenant, _user, workshop, _bom, order = mrp_screens_setup
    with use_tenant(tenant.id):
        workcenter = MrpWorkcenter.objects.create(
            tenant=tenant, workshop=workshop, code="WC-CRI", name="Poste CRI", type="couture"
        )

    response = client.post(
        f"/mrp/{order.id}/",
        {
            "action": "create_cri",
            "cri_workcenter_id": str(workcenter.id),
            "cri_type": "panne",
            "cri_date": "2026-08-20",
            "cri_duration_min": "30",
        },
    )
    assert response.status_code == 302

    with use_tenant(tenant.id):
        assert order.cri_entries.count() == 1


def test_scrap_declare(mrp_screens_setup) -> None:
    client, tenant, _user, _workshop, _bom, order = mrp_screens_setup
    response = client.post(
        f"/mrp/{order.id}/",
        {"action": "create_scrap", "scrap_qty": "2", "scrap_reason": "Defaut tissu"},
    )
    assert response.status_code == 302

    with use_tenant(tenant.id):
        order.refresh_from_db()
        assert order.scraps.count() == 1
        assert order.qty_scrapped == Decimal("2")


def test_bom_line_state_transition(mrp_screens_setup) -> None:
    client, tenant, _user, _workshop, _bom, order = mrp_screens_setup
    response = client.post(f"/mrp/{order.id}/", {"action": "confirm"})
    assert response.status_code == 302

    with use_tenant(tenant.id):
        component = order.components.get()

    response = client.post(
        f"/mrp/{order.id}/",
        {"action": "validate_supplier", "component_id": str(component.id)},
    )
    assert response.status_code == 302

    with use_tenant(tenant.id):
        procurement_state = component.procurement_state
        procurement_state.refresh_from_db()
    assert procurement_state.state == "fournisseur_valide"
