from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.mrp.models import MrpWorkcenter, MrpWorkshop
from apps.mrp.services.bom import activate_bom, add_bom_line, create_bom
from apps.mrp.services.cra import create_cra
from apps.mrp.services.interventions import create_cri, declare_scrap
from apps.mrp.services.orders import (
    confirm_order,
    create_order,
    create_work_order,
    done_work_order,
    start_work_order,
)
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def mrp_reports_setup():
    tenant = Tenant.objects.create(code="UI-MRP-RPT", name="UI MRP Reports Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="ui-mrp-rpt@example.com", password="Str0ngPassw0rd!23"
        )
        workshop = MrpWorkshop.objects.create(tenant=tenant, code="ATL-RPT", name="Atelier RPT")
        workcenter = MrpWorkcenter.objects.create(
            tenant=tenant, workshop=workshop, code="WC-RPT", name="Poste RPT", type="couture"
        )
        bom = create_bom(tenant=tenant, code="BOM-RPT", product_template_id=uuid.uuid4())
        add_bom_line(bom, component_template_id=uuid.uuid4(), qty=Decimal(1))
        activate_bom(bom)
        order = create_order(tenant=tenant, bom=bom, workshop=workshop, qty=Decimal(5))
        confirm_order(order, user)
        work_order = create_work_order(
            order,
            workcenter=workcenter,
            qty_planned=Decimal(5),
            sequence=1,
            duration_planned_min=60,
        )
        start_work_order(work_order, operator=user)
        done_work_order(work_order, qty_done=Decimal(5))

        today = dt.date.today()
        create_cra(
            tenant=tenant,
            employee=user,
            workshop=workshop,
            date=today,
            hours=Decimal(8),
            order=order,
            qty_done=Decimal(5),
        )
        create_cri(
            tenant=tenant,
            type="panne",
            workcenter=workcenter,
            date=today,
            order=order,
            intervenant_user=user,
            duration_min=30,
            downtime_min=15,
        )
        declare_scrap(order, declared_by=user, qty=Decimal(1), reason="Defaut tissu")

    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, workshop, order


def test_reports_index_renders(mrp_reports_setup) -> None:
    client, _tenant, _workshop, _order = mrp_reports_setup
    response = client.get("/mrp/reports/")
    assert response.status_code == 200


def test_report_order_pdf(mrp_reports_setup) -> None:
    client, _tenant, _workshop, order = mrp_reports_setup
    response = client.get(f"/mrp/reports/{order.id}/order.pdf")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_report_cost(mrp_reports_setup) -> None:
    client, _tenant, _workshop, order = mrp_reports_setup
    response = client.get(f"/mrp/reports/{order.id}/cost/")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert b"total_planned" in response.content


def test_report_cra(mrp_reports_setup) -> None:
    client, _tenant, _workshop, _order = mrp_reports_setup
    today = dt.date.today()
    response = client.get(
        "/mrp/reports/cra/",
        {"date_from": today.isoformat(), "date_to": today.isoformat(), "format": "csv"},
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv"
    assert b"employee" in response.content


def test_report_cri(mrp_reports_setup) -> None:
    client, _tenant, _workshop, _order = mrp_reports_setup
    today = dt.date.today()
    response = client.get(
        "/mrp/reports/cri/",
        {"date_from": today.isoformat(), "date_to": today.isoformat(), "format": "json"},
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert b"workcenter" in response.content


def test_report_efficiency(mrp_reports_setup) -> None:
    client, _tenant, _workshop, _order = mrp_reports_setup
    response = client.get("/mrp/reports/efficiency/", {"format": "json"})
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert b"efficiency_pct" in response.content


def test_report_scrap(mrp_reports_setup) -> None:
    client, _tenant, _workshop, _order = mrp_reports_setup
    today = dt.date.today()
    response = client.get(
        "/mrp/reports/scrap/",
        {"date_from": today.isoformat(), "date_to": today.isoformat(), "format": "xlsx"},
    )
    assert response.status_code == 200
    assert (
        response["Content-Type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert len(response.content) > 0


def test_report_workload(mrp_reports_setup) -> None:
    client, _tenant, workshop, _order = mrp_reports_setup
    response = client.get(f"/mrp/reports/workload/{workshop.id}/", {"format": "json"})
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"


def test_reports_require_login(mrp_reports_setup) -> None:
    _client, _tenant, _workshop, order = mrp_reports_setup
    anon_client = Client()
    response = anon_client.get(f"/mrp/reports/{order.id}/order.pdf")
    assert response.status_code == 302
    assert "/login" in response["Location"] or "login" in response["Location"]
