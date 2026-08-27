from __future__ import annotations

import uuid

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.mrp.models import MrpBom, MrpOperation, MrpRouting, MrpWorkcenter, MrpWorkshop
from apps.mrp.services.bom import create_bom
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def mrp_config_setup():
    tenant = Tenant.objects.create(code="UI-MRP-CFG", name="UI MRP Config Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="ui-mrp-cfg@example.com", password="Str0ngPassw0rd!23"
        )
        workshop = MrpWorkshop.objects.create(tenant=tenant, code="ATL-CFG", name="Atelier Config")
        workcenter = MrpWorkcenter.objects.create(
            tenant=tenant,
            workshop=workshop,
            code="WC-CFG",
            name="Poste Config",
            type=MrpWorkcenter.TYPE_SEWING,
        )
        operation = MrpOperation.objects.create(
            tenant=tenant,
            code="OP-CFG",
            name="Operation Config",
            workcenter_type=MrpWorkcenter.TYPE_SEWING,
        )
        routing = MrpRouting.objects.create(tenant=tenant, code="RTG-CFG", name="Gamme Config")
        bom = create_bom(tenant=tenant, code="BOM-CFG", product_template_id=uuid.uuid4())
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, workshop, workcenter, operation, routing, bom


def test_config_index_screen(mrp_config_setup) -> None:
    client, *_ = mrp_config_setup
    response = client.get("/mrp/config/")
    assert response.status_code == 200


def test_create_workshop_via_screen(mrp_config_setup) -> None:
    client, *_ = mrp_config_setup
    response = client.post("/mrp/config/workshops/", {"code": "ATL-NEW", "name": "Nouvel atelier"})
    assert response.status_code == 302
    listing = client.get("/mrp/config/workshops/")
    assert b"ATL-NEW" in listing.content


def test_create_workcenter_via_screen(mrp_config_setup) -> None:
    client, _tenant, workshop, *_ = mrp_config_setup
    response = client.post(
        "/mrp/config/workcenters/",
        {
            "workshop_id": str(workshop.id),
            "code": "WC-NEW",
            "name": "Nouveau poste",
            "type": "couture",
        },
    )
    assert response.status_code == 302
    listing = client.get("/mrp/config/workcenters/")
    assert b"WC-NEW" in listing.content


def test_create_operation_via_screen(mrp_config_setup) -> None:
    client, *_ = mrp_config_setup
    response = client.post(
        "/mrp/config/operations/",
        {"code": "OP-NEW", "name": "Nouvelle operation", "workcenter_type": "couture"},
    )
    assert response.status_code == 302
    listing = client.get("/mrp/config/operations/")
    assert b"OP-NEW" in listing.content


def test_create_routing_then_add_step(mrp_config_setup) -> None:
    client, _tenant, _workshop, workcenter, operation, _routing, _bom = mrp_config_setup
    response = client.post("/mrp/config/routings/", {"code": "RTG-NEW", "name": "Nouvelle gamme"})
    assert response.status_code == 302

    listing = client.get("/mrp/config/routings/")
    assert b"RTG-NEW" in listing.content

    with use_tenant(_tenant.id):
        routing = MrpRouting.objects.get(code="RTG-NEW")
    response = client.post(
        f"/mrp/config/routings/{routing.id}/",
        {
            "sequence": "1",
            "operation_id": str(operation.id),
            "workcenter_id": str(workcenter.id),
            "duration_min": "15",
        },
    )
    assert response.status_code == 302

    detail = client.get(f"/mrp/config/routings/{routing.id}/")
    assert detail.status_code == 200
    with use_tenant(_tenant.id):
        assert routing.steps.count() == 1


def test_bom_create_add_line_activate_and_new_version(mrp_config_setup) -> None:
    client, tenant, *_ = mrp_config_setup
    product_id = str(uuid.uuid4())
    response = client.post(
        "/mrp/config/boms/", {"code": "BOM-NEW", "product_template_id": product_id}
    )
    assert response.status_code == 302
    with use_tenant(tenant.id):
        bom = MrpBom.objects.get(code="BOM-NEW")
        assert bom.state == MrpBom.STATE_DRAFT

    response = client.post(
        f"/mrp/config/boms/{bom.id}/",
        {
            "action": "add_line",
            "sequence": "1",
            "component_template_id": str(uuid.uuid4()),
            "qty": "2",
            "waste_pct": "5",
        },
    )
    assert response.status_code == 302
    with use_tenant(tenant.id):
        bom.refresh_from_db()
        assert bom.lines.count() == 1

    response = client.post(f"/mrp/config/boms/{bom.id}/", {"action": "activate"})
    assert response.status_code == 302
    with use_tenant(tenant.id):
        bom.refresh_from_db()
        assert bom.state == MrpBom.STATE_ACTIVE

    response = client.post(f"/mrp/config/boms/{bom.id}/", {"action": "new_version"})
    assert response.status_code == 302
    with use_tenant(tenant.id):
        new_bom = MrpBom.objects.get(code="BOM-NEW", version=2)
        assert new_bom.state == MrpBom.STATE_DRAFT
        assert new_bom.lines.count() == 1

    detail = client.get(f"/mrp/config/boms/{new_bom.id}/")
    assert detail.status_code == 200
