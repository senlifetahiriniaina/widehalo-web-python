from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, Permission
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
def api_financing():
    # `financing` est scope explicitement a `admin`/`direction`/`comptable`
    # — les 3 SONT dans `CORE_MFA_REQUIRED_ROLES`, ce qui bloquerait la
    # connexion JWT de ce test tant qu'un device TOTP n'est pas enrole
    # (meme constat/meme contournement que `apps.accounting.tests.test_api`,
    # cf. son commentaire) : groupe ad hoc portant les permissions
    # `financing` reellement exercees, plutot que `grant_role("comptable")`.
    tenant = Tenant.objects.create(code="FIN-API", name="Financing API Tenant")
    user = User.objects.create_user(email="financing-api@example.com", password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name="financing-api-test")
    group.permissions.set(
        Permission.objects.filter(
            content_type__app_label="financing",
            codename__in=[
                "view_finloanapplication",
                "add_finloanapplication",
                "change_finloanapplication",
                "view_finguarantee",
                "add_finguarantee",
                "view_fincredoc",
                "add_fincredoc",
                "change_fincredoc",
            ],
        )
    )
    user.groups.add(group)
    return tenant, user


def test_create_and_read_loan_application_via_api(api_financing) -> None:
    tenant, user = api_financing
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/financing/loan-applications",
        {
            "type": "fonctionnement",
            "amount_requested_mga": "15000000",
            "duration_months": 12,
        },
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    application_id = create_response.json()["id"]

    detail_response = client.get(f"/api/v1/financing/loan-applications/{application_id}", **headers)
    assert detail_response.status_code == 200
    assert detail_response.json()["financing_plan_lines"] == []

    line_response = client.post(
        f"/api/v1/financing/loan-applications/{application_id}/financing-plan-lines",
        {"source": "fonds_propres", "amount_mga": "5000000"},
        content_type="application/json",
        **headers,
    )
    assert line_response.status_code == 200

    submit_response = client.post(
        f"/api/v1/financing/loan-applications/{application_id}/submit",
        content_type="application/json",
        **headers,
    )
    assert submit_response.status_code == 200
    assert submit_response.json()["state"] == "submitted"

    decide_response = client.post(
        f"/api/v1/financing/loan-applications/{application_id}/decide",
        {"accepted": True},
        content_type="application/json",
        **headers,
    )
    assert decide_response.status_code == 200
    assert decide_response.json()["state"] == "accepted"


def test_add_guarantee_via_api(api_financing) -> None:
    tenant, user = api_financing
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/financing/loan-applications",
        {"type": "fonctionnement", "amount_requested_mga": "10000000", "duration_months": 12},
        content_type="application/json",
        **headers,
    )
    application_id = create_response.json()["id"]

    guarantee_response = client.post(
        f"/api/v1/financing/loan-applications/{application_id}/guarantees",
        {"type": "hypotheque", "estimated_value_mga": "12000000"},
        content_type="application/json",
        **headers,
    )
    assert guarantee_response.status_code == 200

    list_response = client.get(
        f"/api/v1/financing/loan-applications/{application_id}/guarantees", **headers
    )
    assert list_response.status_code == 200
    body = list_response.json()
    assert len(body["results"]) == 1
    assert body["coverage"]["is_covered"] is True


def test_credoc_lifecycle_via_api(api_financing) -> None:
    import uuid

    tenant, user = api_financing
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/financing/credocs",
        {
            "purchase_order_id": str(uuid.uuid4()),
            "bank": "Banque emettrice",
            "beneficiary": "Fournisseur import",
            "amount_mga": "30000000",
            "validity_date": "2026-12-31",
        },
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    credoc_id = create_response.json()["id"]
    assert create_response.json()["state"] == "demande"

    open_response = client.post(
        f"/api/v1/financing/credocs/{credoc_id}/transition/open",
        content_type="application/json",
        **headers,
    )
    assert open_response.status_code == 200
    assert open_response.json()["state"] == "ouvert"


def test_role_without_financing_permission_is_denied(api_financing) -> None:
    tenant, _user = api_financing
    other = User.objects.create_user(email="collab@example.com", password="Str0ngPassw0rd!23")
    grant_role(other, "collaborateur")
    client = Client()
    token = _access_token(client, other.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get("/api/v1/financing/loan-applications", **headers)
    assert response.status_code == 403
