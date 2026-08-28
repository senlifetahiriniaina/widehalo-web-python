from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.purchase.services.orders import add_order_line, create_order
from apps.purchase.services.rfq import add_rfq_line, create_rfq
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def purchase_reports_setup():
    tenant = Tenant.objects.create(code="UI-PUR-RPT", name="UI Purchase Reports Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="ui-pur-rpt@example.com", password="Str0ngPassw0rd!23"
        )
        order = create_order(
            tenant=tenant,
            partner_id=uuid.uuid4(),
            date=dt.date.today(),
            date_expected=dt.date.today() - dt.timedelta(days=3),
        )
        add_order_line(
            order,
            variant_id=uuid.uuid4(),
            description="Doublure",
            qty=Decimal(20),
            unit_price_mga=Decimal(1500),
        )
        rfq = create_rfq(tenant=tenant, date=dt.date.today())
        add_rfq_line(rfq, variant_id=uuid.uuid4(), description="Doublure", qty=Decimal(20))
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, order, rfq


def test_reports_index_renders(purchase_reports_setup) -> None:
    client, *_ = purchase_reports_setup
    response = client.get("/purchase/reports/")
    assert response.status_code == 200


def test_report_order_pdf(purchase_reports_setup) -> None:
    client, _tenant, order, _rfq = purchase_reports_setup
    response = client.get(f"/purchase/reports/orders/{order.id}/bc.pdf")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_report_rfq(purchase_reports_setup) -> None:
    client, _tenant, _order, rfq = purchase_reports_setup
    response = client.get(f"/purchase/reports/rfqs/{rfq.id}/", {"format": "json"})
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert b"Doublure" in response.content


def test_report_rfq_comparison(purchase_reports_setup) -> None:
    client, _tenant, _order, rfq = purchase_reports_setup
    response = client.get(f"/purchase/reports/rfqs/{rfq.id}/comparison/", {"format": "json"})
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"


def test_report_reception(purchase_reports_setup) -> None:
    client, _tenant, order, _rfq = purchase_reports_setup
    response = client.get(f"/purchase/reports/orders/{order.id}/reception/", {"format": "csv"})
    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv"


def test_report_engagements(purchase_reports_setup) -> None:
    client, *_ = purchase_reports_setup
    response = client.get("/purchase/reports/engagements/", {"format": "json"})
    assert response.status_code == 200
    assert b"amount_total_mga" in response.content


def test_report_supplier_evaluations(purchase_reports_setup) -> None:
    client, *_ = purchase_reports_setup
    response = client.get(
        "/purchase/reports/supplier-evaluations/",
        {"partner_id": str(uuid.uuid4()), "format": "json"},
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"


def test_report_late_orders(purchase_reports_setup) -> None:
    client, *_ = purchase_reports_setup
    response = client.get("/purchase/reports/late-orders/", {"format": "xlsx"})
    assert response.status_code == 200
    assert (
        response["Content-Type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert len(response.content) > 0


def test_report_cri(purchase_reports_setup) -> None:
    client, *_ = purchase_reports_setup
    response = client.get("/purchase/reports/cri/", {"format": "json"})
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"


def test_reports_require_login(purchase_reports_setup) -> None:
    _client, _tenant, order, _rfq = purchase_reports_setup
    anon_client = Client()
    response = anon_client.get(f"/purchase/reports/orders/{order.id}/bc.pdf")
    assert response.status_code == 302
    assert "login" in response["Location"]
