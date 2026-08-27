from __future__ import annotations

import calendar
import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.test import Client

from apps.accounting.models import AccAccount, AccJournal
from apps.accounting.tests.factories import AccAccountFactory, AccJournalFactory, AccPeriodFactory
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.sales.models import SalesOrder
from apps.sales.services.orders import mark_delivered, start_preparation

pytestmark = pytest.mark.django_db


def _access_token(client: Client, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        {"email": email, "password": password},
        content_type="application/json",
    )
    return response.json()["access"]


def _headers(token: str, tenant_id: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": tenant_id}


@pytest.fixture
def api_sales():
    tenant = Tenant.objects.create(code="SALES-API", name="Sales API Tenant")
    user = User.objects.create_user(email="sales-api@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "commercial")
    return tenant, user


def test_create_and_get_quotation_via_api(api_sales) -> None:
    tenant, user = api_sales
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/sales/quotations",
        {
            "partner_id": str(uuid.uuid4()),
            "date": str(dt.date.today()),
            "lines": [
                {
                    "description": "Prestation sur mesure",
                    "qty": "2",
                    "unit_price": "10000",
                    "is_custom": True,
                }
            ],
        },
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    body = create_response.json()
    quotation_id = body["id"]
    assert body["reference"].startswith("DEVIS-")
    assert body["state"] == "draft"
    assert Decimal(body["amount_total"]) == Decimal("20000.0000")

    get_response = client.get(f"/api/v1/sales/quotations/{quotation_id}", **headers)
    assert get_response.status_code == 200
    assert get_response.json()["reference"] == body["reference"]


def test_list_quotations_via_api(api_sales) -> None:
    tenant, user = api_sales
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    client.post(
        "/api/v1/sales/quotations",
        {"partner_id": str(uuid.uuid4()), "date": str(dt.date.today())},
        content_type="application/json",
        **headers,
    )
    response = client.get("/api/v1/sales/quotations", **headers)
    assert response.status_code == 200
    assert len(response.json()["results"]) == 1


def test_add_line_and_send_accept_quotation_via_api(api_sales) -> None:
    tenant, user = api_sales
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/sales/quotations",
        {"partner_id": str(uuid.uuid4()), "date": str(dt.date.today())},
        content_type="application/json",
        **headers,
    )
    quotation_id = create_response.json()["id"]

    line_response = client.post(
        f"/api/v1/sales/quotations/{quotation_id}/lines",
        {
            "description": "Prestation",
            "qty": "1",
            "unit_price": "5000",
            "is_custom": True,
        },
        content_type="application/json",
        **headers,
    )
    assert line_response.status_code == 200
    assert Decimal(line_response.json()["amount_total"]) == Decimal("5000.0000")

    send_response = client.post(
        f"/api/v1/sales/quotations/{quotation_id}/send", content_type="application/json", **headers
    )
    assert send_response.status_code == 200
    assert send_response.json()["state"] == "sent"

    accept_response = client.post(
        f"/api/v1/sales/quotations/{quotation_id}/accept",
        content_type="application/json",
        **headers,
    )
    assert accept_response.status_code == 200
    assert accept_response.json()["state"] == "accepted"


def test_decline_quotation_via_api(api_sales) -> None:
    tenant, user = api_sales
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/sales/quotations",
        {"partner_id": str(uuid.uuid4()), "date": str(dt.date.today())},
        content_type="application/json",
        **headers,
    )
    quotation_id = create_response.json()["id"]
    client.post(
        f"/api/v1/sales/quotations/{quotation_id}/send", content_type="application/json", **headers
    )
    decline_response = client.post(
        f"/api/v1/sales/quotations/{quotation_id}/decline",
        {"reason": "Trop cher"},
        content_type="application/json",
        **headers,
    )
    assert decline_response.status_code == 200
    assert decline_response.json()["state"] == "declined"


def test_send_quotation_rejects_non_draft_via_api(api_sales) -> None:
    tenant, user = api_sales
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/sales/quotations",
        {"partner_id": str(uuid.uuid4()), "date": str(dt.date.today())},
        content_type="application/json",
        **headers,
    )
    quotation_id = create_response.json()["id"]
    client.post(
        f"/api/v1/sales/quotations/{quotation_id}/send", content_type="application/json", **headers
    )
    second_send_response = client.post(
        f"/api/v1/sales/quotations/{quotation_id}/send", content_type="application/json", **headers
    )
    assert second_send_response.status_code == 400


def test_create_and_get_order_via_api(api_sales) -> None:
    tenant, user = api_sales
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/sales/orders",
        {
            "partner_id": str(uuid.uuid4()),
            "date": str(dt.date.today()),
            "lines": [
                {
                    "description": "Prestation sur mesure",
                    "qty": "2",
                    "unit_price": "10000",
                    "is_custom": True,
                }
            ],
        },
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    body = create_response.json()
    order_id = body["id"]
    assert body["reference"].startswith("CMD-")
    assert body["state"] == "draft"
    assert Decimal(body["amount_total"]) == Decimal("20000.0000")

    get_response = client.get(f"/api/v1/sales/orders/{order_id}", **headers)
    assert get_response.status_code == 200
    assert get_response.json()["reference"] == body["reference"]


def test_list_orders_via_api(api_sales) -> None:
    tenant, user = api_sales
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    client.post(
        "/api/v1/sales/orders",
        {"partner_id": str(uuid.uuid4()), "date": str(dt.date.today())},
        content_type="application/json",
        **headers,
    )
    response = client.get("/api/v1/sales/orders", **headers)
    assert response.status_code == 200
    assert len(response.json()["results"]) == 1


def test_confirm_and_deliver_order_via_api(api_sales) -> None:
    tenant, user = api_sales
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/sales/orders",
        {"partner_id": str(uuid.uuid4()), "date": str(dt.date.today())},
        content_type="application/json",
        **headers,
    )
    order_id = create_response.json()["id"]

    confirm_response = client.post(
        f"/api/v1/sales/orders/{order_id}/confirm", content_type="application/json", **headers
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json()["state"] == "confirmed"

    with use_tenant(tenant.id):
        order = SalesOrder.objects.get(id=order_id)
        start_preparation(order, user)

    deliver_response = client.post(
        f"/api/v1/sales/orders/{order_id}/deliver",
        {"partial": False},
        content_type="application/json",
        **headers,
    )
    assert deliver_response.status_code == 200
    assert deliver_response.json()["state"] == "delivered"

    # Une commande livree ne peut plus etre annulee directement (garde
    # miroir de `accounting.services.invoices.cancel_invoice`).
    cancel_response = client.post(
        f"/api/v1/sales/orders/{order_id}/cancel",
        {"reason": "Client annule"},
        content_type="application/json",
        **headers,
    )
    assert cancel_response.status_code == 400


def test_cancel_order_requires_reason_via_api(api_sales) -> None:
    tenant, user = api_sales
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/sales/orders",
        {"partner_id": str(uuid.uuid4()), "date": str(dt.date.today())},
        content_type="application/json",
        **headers,
    )
    order_id = create_response.json()["id"]
    cancel_response = client.post(
        f"/api/v1/sales/orders/{order_id}/cancel",
        {"reason": ""},
        content_type="application/json",
        **headers,
    )
    assert cancel_response.status_code == 400


def test_invoice_order_via_api_success_transitions_to_invoiced(api_sales) -> None:
    tenant, user = api_sales
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    with use_tenant(tenant.id):
        AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_SALE)
        today = dt.date.today()
        last_day = calendar.monthrange(today.year, today.month)[1]
        AccPeriodFactory(
            tenant=tenant,
            date_start=today.replace(day=1),
            date_end=today.replace(day=last_day),
        )
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_RECEIVABLE)
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_INCOME)

    create_response = client.post(
        "/api/v1/sales/orders",
        {
            "partner_id": str(uuid.uuid4()),
            "date": str(dt.date.today()),
            "lines": [
                {
                    "description": "Prestation sur mesure",
                    "qty": "2",
                    "unit_price": "10000",
                    "is_custom": True,
                }
            ],
        },
        content_type="application/json",
        **headers,
    )
    order_id = create_response.json()["id"]

    client.post(
        f"/api/v1/sales/orders/{order_id}/confirm", content_type="application/json", **headers
    )
    with use_tenant(tenant.id):
        order = SalesOrder.objects.get(id=order_id)
        start_preparation(order, user)
        mark_delivered(order, user)

    invoice_response = client.post(
        f"/api/v1/sales/orders/{order_id}/invoice", content_type="application/json", **headers
    )
    assert invoice_response.status_code == 200
    body = invoice_response.json()
    assert body["invoice_id"] is not None

    get_response = client.get(f"/api/v1/sales/orders/{order_id}", **headers)
    assert get_response.json()["state"] == "invoiced"
    assert Decimal(get_response.json()["invoiced_amount_mga"]) == Decimal("20000.0000")


def test_invoice_order_via_api_returns_none_without_accounting_config(api_sales) -> None:
    tenant, user = api_sales
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/sales/orders",
        {
            "partner_id": str(uuid.uuid4()),
            "date": str(dt.date.today()),
            "lines": [
                {"description": "Prestation", "qty": "1", "unit_price": "5000", "is_custom": True}
            ],
        },
        content_type="application/json",
        **headers,
    )
    order_id = create_response.json()["id"]
    client.post(
        f"/api/v1/sales/orders/{order_id}/confirm", content_type="application/json", **headers
    )
    with use_tenant(tenant.id):
        order = SalesOrder.objects.get(id=order_id)
        start_preparation(order, user)
        mark_delivered(order, user)

    invoice_response = client.post(
        f"/api/v1/sales/orders/{order_id}/invoice", content_type="application/json", **headers
    )
    assert invoice_response.status_code == 200
    body = invoice_response.json()
    assert body["invoice_id"] is None
    assert body["detail"]

    get_response = client.get(f"/api/v1/sales/orders/{order_id}", **headers)
    assert get_response.json()["state"] == "delivered"


def test_invoice_order_via_api_denied_without_permission(api_sales) -> None:
    tenant, user = api_sales
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/sales/orders",
        {"partner_id": str(uuid.uuid4()), "date": str(dt.date.today())},
        content_type="application/json",
        **headers,
    )
    order_id = create_response.json()["id"]

    outsider = User.objects.create_user(
        email="sales-invoice-outsider@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(outsider, "collaborateur")
    outsider_token = _access_token(client, outsider.email, "Str0ngPassw0rd!23")
    outsider_headers = _headers(outsider_token, str(tenant.id))

    response = client.post(
        f"/api/v1/sales/orders/{order_id}/invoice",
        content_type="application/json",
        **outsider_headers,
    )
    assert response.status_code == 403


def test_create_order_via_api_denied_without_permission(api_sales) -> None:
    """Regression T6/RBAC : require_permission("sales.add_salesorder")
    doit refuser (403) un utilisateur authentifie sans ce role."""
    tenant, _user = api_sales
    client = Client()
    outsider = User.objects.create_user(
        email="sales-order-outsider@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(outsider, "collaborateur")
    token = _access_token(client, outsider.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/sales/orders",
        {"partner_id": str(uuid.uuid4()), "date": str(dt.date.today())},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 403


def test_create_quotation_via_api_denied_without_permission(api_sales) -> None:
    """Regression T6/RBAC : require_permission("sales.add_salesquotation")
    doit refuser (403) un utilisateur authentifie sans ce role — ici un
    "collaborateur", role par defaut sans acces au module sales."""
    tenant, _user = api_sales
    client = Client()
    outsider = User.objects.create_user(
        email="sales-outsider@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(outsider, "collaborateur")
    token = _access_token(client, outsider.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/sales/quotations",
        {"partner_id": str(uuid.uuid4()), "date": str(dt.date.today())},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 403


def test_create_and_list_recurrences_via_api(api_sales) -> None:
    tenant, user = api_sales
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    order_response = client.post(
        "/api/v1/sales/orders",
        {"partner_id": str(uuid.uuid4()), "date": str(dt.date.today())},
        content_type="application/json",
        **headers,
    )
    template_order_id = order_response.json()["id"]

    create_response = client.post(
        "/api/v1/sales/recurrences",
        {
            "name": "Facturation mensuelle",
            "interval": "monthly",
            "start_date": str(dt.date.today()),
            "template_order_id": template_order_id,
        },
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    body = create_response.json()
    assert body["name"] == "Facturation mensuelle"
    assert body["interval"] == "monthly"
    assert body["template_order_id"] == template_order_id
    assert body["is_active"] is True

    list_response = client.get("/api/v1/sales/recurrences", **headers)
    assert list_response.status_code == 200
    results = list_response.json()["results"]
    assert any(item["id"] == body["id"] for item in results)


def test_create_recurrence_via_api_denied_without_permission(api_sales) -> None:
    """Regression T6/RBAC : require_permission("sales.add_salesrecurrence")
    doit refuser (403) un utilisateur authentifie sans ce role."""
    tenant, user = api_sales
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    order_response = client.post(
        "/api/v1/sales/orders",
        {"partner_id": str(uuid.uuid4()), "date": str(dt.date.today())},
        content_type="application/json",
        **headers,
    )
    template_order_id = order_response.json()["id"]

    outsider = User.objects.create_user(
        email="sales-recurrence-outsider@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(outsider, "collaborateur")
    outsider_token = _access_token(client, outsider.email, "Str0ngPassw0rd!23")
    outsider_headers = _headers(outsider_token, str(tenant.id))

    response = client.post(
        "/api/v1/sales/recurrences",
        {
            "name": "Facturation mensuelle",
            "interval": "monthly",
            "start_date": str(dt.date.today()),
            "template_order_id": template_order_id,
        },
        content_type="application/json",
        **outsider_headers,
    )
    assert response.status_code == 403
