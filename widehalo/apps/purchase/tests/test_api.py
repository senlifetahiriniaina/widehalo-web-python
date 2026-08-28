from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.test import Client

from apps.catalog.models import ProductTemplate, ProductVariant, UnitOfMeasure
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant

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
def api_purchase():
    tenant = Tenant.objects.create(code="PUR-API", name="Purchase API Tenant")
    user = User.objects.create_user(email="purchase-api@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "acheteur")
    with use_tenant(tenant.id):
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PC", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )
        template = ProductTemplate.objects.create(
            tenant=tenant,
            name="Fil polyester",
            base_uom=uom,
            reference="TPL-PUR-API-0001",
            base_price_mga=Decimal("1200"),
        )
        variant = ProductVariant.objects.create(
            tenant=tenant, template=template, reference="VAR-PUR-API-0001"
        )
    return tenant, user, variant


def test_create_and_get_requisition_via_api(api_purchase) -> None:
    tenant, user, variant = api_purchase
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/purchase/requisitions",
        {
            "date_needed": str(dt.date.today()),
            "department": "Production",
            "lines": [
                {
                    "variant_id": str(variant.id),
                    "description": "Fil polyester",
                    "qty": "20",
                }
            ],
        },
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    body = create_response.json()
    requisition_id = body["id"]
    assert body["reference"].startswith("PREQ-")
    assert body["state"] == "draft"
    assert len(body["lines"]) == 1

    get_response = client.get(f"/api/v1/purchase/requisitions/{requisition_id}", **headers)
    assert get_response.status_code == 200
    assert get_response.json()["reference"] == body["reference"]


def test_list_requisitions_via_api(api_purchase) -> None:
    tenant, user, _variant = api_purchase
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    client.post(
        "/api/v1/purchase/requisitions",
        {"date_needed": str(dt.date.today())},
        content_type="application/json",
        **headers,
    )

    list_response = client.get("/api/v1/purchase/requisitions", **headers)
    assert list_response.status_code == 200
    assert len(list_response.json()["results"]) == 1


def test_add_line_submit_and_approve_via_api(api_purchase) -> None:
    tenant, user, variant = api_purchase
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/purchase/requisitions",
        {"date_needed": str(dt.date.today())},
        content_type="application/json",
        **headers,
    )
    requisition_id = create_response.json()["id"]

    line_response = client.post(
        f"/api/v1/purchase/requisitions/{requisition_id}/lines",
        {"variant_id": str(variant.id), "description": "Boutons", "qty": "500"},
        content_type="application/json",
        **headers,
    )
    assert line_response.status_code == 200
    assert len(line_response.json()["lines"]) == 1

    submit_response = client.post(
        f"/api/v1/purchase/requisitions/{requisition_id}/submit", **headers
    )
    assert submit_response.status_code == 200
    assert submit_response.json()["state"] == "submitted"

    # Re-fetch entre deux appels HTTP : l'etat doit bien avoir persiste.
    get_response = client.get(f"/api/v1/purchase/requisitions/{requisition_id}", **headers)
    assert get_response.json()["state"] == "submitted"

    approve_response = client.post(
        f"/api/v1/purchase/requisitions/{requisition_id}/approve", **headers
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["state"] == "approved"

    get_response = client.get(f"/api/v1/purchase/requisitions/{requisition_id}", **headers)
    assert get_response.json()["state"] == "approved"


def test_reject_requisition_via_api_requires_reason(api_purchase) -> None:
    tenant, user, variant = api_purchase
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/purchase/requisitions",
        {"date_needed": str(dt.date.today())},
        content_type="application/json",
        **headers,
    )
    requisition_id = create_response.json()["id"]
    client.post(
        f"/api/v1/purchase/requisitions/{requisition_id}/lines",
        {"variant_id": str(variant.id), "description": "Boutons", "qty": "500"},
        content_type="application/json",
        **headers,
    )
    client.post(f"/api/v1/purchase/requisitions/{requisition_id}/submit", **headers)

    bad_response = client.post(
        f"/api/v1/purchase/requisitions/{requisition_id}/reject",
        {"reason": ""},
        content_type="application/json",
        **headers,
    )
    assert bad_response.status_code == 400

    good_response = client.post(
        f"/api/v1/purchase/requisitions/{requisition_id}/reject",
        {"reason": "Fournisseur non retenu"},
        content_type="application/json",
        **headers,
    )
    assert good_response.status_code == 200
    assert good_response.json()["state"] == "rejected"

    get_response = client.get(f"/api/v1/purchase/requisitions/{requisition_id}", **headers)
    assert get_response.json()["state"] == "rejected"


def test_purchase_order_fsm_state_persists_across_separate_api_calls(api_purchase) -> None:
    """Discipline T7 (garde-fou architecture `attempt_transition`+`.save()`)
    : chaque transition est verifiee via un rechargement HTTP separe, pas
    en reutilisant le meme objet Python en memoire — c'est exactement ce
    type de test qui avait detecte la regression reelle dans `mrp`."""
    tenant, user, variant = api_purchase
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/purchase/orders",
        {
            "partner_id": str(uuid.uuid4()),
            "date": str(dt.date.today()),
            "lines": [
                {
                    "variant_id": str(variant.id),
                    "description": "Fil polyester",
                    "qty": "10",
                    "unit_price_mga": "1000",
                }
            ],
        },
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    body = create_response.json()
    order_id = body["id"]
    assert body["reference"].startswith("PCMD-")
    assert body["state"] == "draft"

    submit_response = client.post(f"/api/v1/purchase/orders/{order_id}/submit", **headers)
    assert submit_response.status_code == 200
    assert submit_response.json()["state"] == "to_validate"

    get_response = client.get(f"/api/v1/purchase/orders/{order_id}", **headers)
    assert get_response.json()["state"] == "to_validate"

    validate_response = client.post(f"/api/v1/purchase/orders/{order_id}/validate", **headers)
    assert validate_response.status_code == 200
    assert validate_response.json()["state"] == "validated"

    get_response = client.get(f"/api/v1/purchase/orders/{order_id}", **headers)
    assert get_response.json()["state"] == "validated"

    send_response = client.post(f"/api/v1/purchase/orders/{order_id}/send", **headers)
    assert send_response.status_code == 200
    assert send_response.json()["state"] == "sent"

    get_response = client.get(f"/api/v1/purchase/orders/{order_id}", **headers)
    assert get_response.json()["state"] == "sent"

    confirm_response = client.post(f"/api/v1/purchase/orders/{order_id}/confirm", **headers)
    assert confirm_response.status_code == 200
    assert confirm_response.json()["state"] == "confirmed"

    get_response = client.get(f"/api/v1/purchase/orders/{order_id}", **headers)
    assert get_response.json()["state"] == "confirmed"


def test_create_requisition_via_api_refuses_role_without_purchase_access(api_purchase) -> None:
    tenant, _user, _variant = api_purchase
    outsider = User.objects.create_user(
        email="outsider-purchase@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(outsider, "collaborateur")
    client = Client()
    token = _access_token(client, outsider.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/purchase/requisitions",
        {"date_needed": str(dt.date.today())},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 403
