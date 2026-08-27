from __future__ import annotations

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.mrp.models import MrpWorkshop

pytestmark = pytest.mark.django_db


def _access_token(client: Client, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        {"email": email, "password": password},
        content_type="application/json",
    )
    return response.json()["access"]


@pytest.fixture
def api_mrp():
    tenant = Tenant.objects.create(code="MRP-API", name="MRP API Tenant")
    user = User.objects.create_user(email="mrp-api@example.com", password="Str0ngPassw0rd!23")
    with use_tenant(tenant.id):
        workshop = MrpWorkshop.objects.create(tenant=tenant, code="ATL-1", name="Atelier")
    return tenant, user, workshop


def _headers(token: str, tenant_id: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": tenant_id}


def test_create_bom_and_order_and_run_workflow_via_api(api_mrp) -> None:
    tenant, user, workshop = api_mrp
    grant_role(user, "resp_production")
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    bom_response = client.post(
        "/api/v1/mrp/boms",
        {"code": "BOM-API-1", "product_template_id": "11111111-1111-1111-1111-111111111111"},
        content_type="application/json",
        **headers,
    )
    assert bom_response.status_code == 200
    bom_id = bom_response.json()["id"]
    assert bom_response.json()["state"] == "active"

    order_response = client.post(
        "/api/v1/mrp/orders",
        {"bom_id": bom_id, "workshop_id": str(workshop.id), "qty": "5"},
        content_type="application/json",
        **headers,
    )
    assert order_response.status_code == 200
    order_id = order_response.json()["id"]
    assert order_response.json()["state"] == "draft"

    confirm_response = client.post(f"/api/v1/mrp/orders/{order_id}/confirm", **headers)
    assert confirm_response.status_code == 200
    assert confirm_response.json()["state"] == "confirmed"

    reserve_response = client.post(f"/api/v1/mrp/orders/{order_id}/reserve", **headers)
    assert reserve_response.json()["state"] == "reserved"


def test_list_workshops_via_api(api_mrp) -> None:
    tenant, user, workshop = api_mrp
    grant_role(user, "resp_production")
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get("/api/v1/mrp/workshops", **headers)
    assert response.status_code == 200
    codes = {w["code"] for w in response.json()["results"]}
    assert workshop.code in codes


def test_create_order_denied_without_role(api_mrp) -> None:
    tenant, user, workshop = api_mrp
    grant_role(user, "collaborateur")
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/mrp/orders",
        {
            "bom_id": "11111111-1111-1111-1111-111111111111",
            "workshop_id": str(workshop.id),
            "qty": "5",
        },
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 403
