from __future__ import annotations

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role
from apps.stocks.models import StkDefectType, StkLocation, StkWarehouse

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
def api_stocks():
    tenant = Tenant.objects.create(code="STK-API", name="Stocks API Tenant")
    user = User.objects.create_user(
        email="magasinier-api@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(user, "magasinier")
    return tenant, user


def test_create_and_list_warehouse_via_api(api_stocks) -> None:
    tenant, user = api_stocks
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/stocks/warehouses",
        {"code": "WH-01", "name": "Entrepot principal", "type": StkWarehouse.TYPE_PRINCIPAL},
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    body = create_response.json()
    assert body["code"] == "WH-01"
    assert body["type"] == StkWarehouse.TYPE_PRINCIPAL

    list_response = client.get("/api/v1/stocks/warehouses", **headers)
    assert list_response.status_code == 200
    assert len(list_response.json()["results"]) == 1


def test_create_location_via_api_with_parent_validation(api_stocks) -> None:
    tenant, user = api_stocks
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    warehouse_response = client.post(
        "/api/v1/stocks/warehouses",
        {"code": "WH-01", "name": "Entrepot principal"},
        content_type="application/json",
        **headers,
    )
    warehouse_id = warehouse_response.json()["id"]

    other_warehouse_response = client.post(
        "/api/v1/stocks/warehouses",
        {"code": "WH-02", "name": "Entrepot secondaire"},
        content_type="application/json",
        **headers,
    )
    other_warehouse_id = other_warehouse_response.json()["id"]

    location_response = client.post(
        "/api/v1/stocks/locations",
        {
            "warehouse_id": warehouse_id,
            "code": "A1",
            "name": "Rayon A1",
            "type": StkLocation.TYPE_INTERNE,
        },
        content_type="application/json",
        **headers,
    )
    assert location_response.status_code == 200
    location_id = location_response.json()["id"]

    invalid_child_response = client.post(
        "/api/v1/stocks/locations",
        {
            "warehouse_id": other_warehouse_id,
            "code": "B1",
            "name": "Rayon B1",
            "parent_id": location_id,
        },
        content_type="application/json",
        **headers,
    )
    assert invalid_child_response.status_code == 400

    list_response = client.get("/api/v1/stocks/locations", **headers)
    assert list_response.status_code == 200
    assert len(list_response.json()["results"]) == 1


def test_create_defect_type_via_api(api_stocks) -> None:
    tenant, user = api_stocks
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/stocks/defect-types",
        {
            "code": "DEF-01",
            "name": "Trou tissu",
            "category": StkDefectType.CATEGORY_TISSU,
            "severity": StkDefectType.SEVERITY_MAJEUR,
        },
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["category"] == StkDefectType.CATEGORY_TISSU
    assert body["severity"] == StkDefectType.SEVERITY_MAJEUR


def test_create_warehouse_via_api_refuses_role_without_stocks_access(api_stocks) -> None:
    tenant, _user = api_stocks
    outsider = User.objects.create_user(
        email="outsider-stocks@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(outsider, "collaborateur")
    client = Client()
    token = _access_token(client, outsider.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/stocks/warehouses",
        {"code": "WH-01", "name": "Entrepot principal"},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 403
