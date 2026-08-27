from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role

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
