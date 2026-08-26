from __future__ import annotations

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User

pytestmark = pytest.mark.django_db


def _access_token(client: Client, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        {"email": email, "password": password},
        content_type="application/json",
    )
    return response.json()["access"]


def test_create_and_list_partners_via_api() -> None:
    tenant = Tenant.objects.create(code="PART-API", name="Partners API Tenant")
    user = User.objects.create_user(email="part-api@example.com", password="Str0ngPassw0rd!23")
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": str(tenant.id)}

    create_response = client.post(
        "/api/v1/partners",
        {"name": "Textile Import Export", "roles": ["client"], "nif": "NIF-API-1"},
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    assert create_response.json()["reference"].startswith("PART-")

    list_response = client.get("/api/v1/partners", **headers)
    assert list_response.status_code == 200
    assert len(list_response.json()["results"]) == 1
