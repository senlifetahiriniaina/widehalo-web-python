from __future__ import annotations

import pytest
from django.test import Client

from apps.catalog.models import UnitOfMeasure
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def _access_token(client: Client, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        {"email": email, "password": password},
        content_type="application/json",
    )
    return response.json()["access"]


def test_create_template_and_read_default_price_via_api() -> None:
    tenant = Tenant.objects.create(code="CAT-API", name="Catalog API Tenant")
    user = User.objects.create_user(email="cat-api@example.com", password="Str0ngPassw0rd!23")
    with use_tenant(tenant.id):
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PC", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )

    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": str(tenant.id)}

    create_response = client.post(
        "/api/v1/catalog/templates",
        {"name": "Pantalon", "base_uom_id": str(uom.id), "base_price_mga": 25000},
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    body = create_response.json()
    assert body["base_price_mga"] == "25000"

    list_response = client.get("/api/v1/catalog/templates", **headers)
    assert list_response.status_code == 200
    assert len(list_response.json()["results"]) == 1
