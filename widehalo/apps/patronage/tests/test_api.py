from __future__ import annotations

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.patronage.models import PatSizeChart

pytestmark = pytest.mark.django_db


def _access_token(client: Client, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        {"email": email, "password": password},
        content_type="application/json",
    )
    return response.json()["access"]


@pytest.fixture
def api_patronage():
    tenant = Tenant.objects.create(code="PAT-API", name="Patronage API Tenant")
    user = User.objects.create_user(email="pat-api@example.com", password="Str0ngPassw0rd!23")
    with use_tenant(tenant.id):
        size_chart = PatSizeChart.objects.create(
            tenant=tenant,
            code="TSHIRT-U",
            name="T-shirt unisexe",
            garment_type=PatSizeChart.GARMENT_TSHIRT,
            sizes=["S", "M"],
            base_size="S",
        )
    return tenant, user, size_chart


def _headers(token: str, tenant_id: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": tenant_id}


def test_create_pattern_and_add_piece_via_api(api_patronage) -> None:
    tenant, user, size_chart = api_patronage
    grant_role(user, "resp_production")
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/patronage/patterns",
        {"code": "PAT-API-1", "name": "T-shirt API", "size_chart_id": str(size_chart.id)},
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    pattern_id = create_response.json()["id"]
    assert create_response.json()["state"] == "draft"

    piece_response = client.post(
        f"/api/v1/patronage/patterns/{pattern_id}/pieces",
        {"code": "devant", "name": "Devant"},
        content_type="application/json",
        **headers,
    )
    assert piece_response.status_code == 200

    validate_response = client.post(f"/api/v1/patronage/patterns/{pattern_id}/validate", **headers)
    assert validate_response.status_code == 200
    assert validate_response.json()["state"] == "validated"


def test_list_size_charts_via_api(api_patronage) -> None:
    tenant, user, size_chart = api_patronage
    grant_role(user, "resp_production")
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get("/api/v1/patronage/size-charts", **headers)
    assert response.status_code == 200
    codes = {s["code"] for s in response.json()["results"]}
    assert size_chart.code in codes


def test_validate_pattern_denied_without_role(api_patronage) -> None:
    tenant, user, size_chart = api_patronage
    grant_role(user, "resp_production")
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/patronage/patterns",
        {"code": "PAT-API-2", "name": "T-shirt API 2", "size_chart_id": str(size_chart.id)},
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    pattern_id = create_response.json()["id"]

    other_user = User.objects.create_user(
        email="pat-api-noaccess@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(other_user, "collaborateur")
    other_token = _access_token(client, other_user.email, "Str0ngPassw0rd!23")
    other_headers = _headers(other_token, str(tenant.id))

    response = client.post(f"/api/v1/patronage/patterns/{pattern_id}/validate", **other_headers)
    assert response.status_code == 403
