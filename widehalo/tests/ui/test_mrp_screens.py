from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.mrp.models import MrpWorkshop
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
