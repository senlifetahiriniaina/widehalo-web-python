from __future__ import annotations

import pytest
from django.test import Client

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
def api_feasibility():
    # "resp_commercial" n'est pas dans CORE_MFA_REQUIRED_ROLES et fait
    # partie des roles "domaine cible" retenus par le cadrage RBAC FEA1-3
    # (cf. `apps.core.services.rbac_policy`).
    tenant = Tenant.objects.create(code="FEA-API", name="Feasibility API Tenant")
    user = User.objects.create_user(
        email="feasibility-api@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(user, "resp_commercial")
    with use_tenant(tenant.id):
        pass
    return tenant, user


def test_create_study_add_line_and_simulate_via_api(api_feasibility) -> None:
    tenant, user = api_feasibility
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/feasibility/studies",
        {"name": "Chaussures en cuir vegetal", "sector_code": "cuir"},
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    study_id = create_response.json()["id"]

    line_response = client.post(
        f"/api/v1/feasibility/studies/{study_id}/lines",
        {
            "hypothetical_spec": {"name": "Chaussure modele A"},
            "assumed_qty": "50",
            "assumed_unit_price_mga": "120000",
        },
        content_type="application/json",
        **headers,
    )
    assert line_response.status_code == 200
    line_id = line_response.json()["id"]

    simulate_response = client.post(
        f"/api/v1/feasibility/lines/{line_id}/simulate",
        {"overhead_rate_pct": "0"},
        content_type="application/json",
        **headers,
    )
    assert simulate_response.status_code == 200
    # Aucun cout manuel/BOM saisi -> total 0, marge non calculable a 100%
    # au sens metier (revenu=6000000, cout=0 -> marge 100%).
    assert simulate_response.json()["computed_margin_pct"] == "100.00"

    detail_response = client.get(f"/api/v1/feasibility/studies/{study_id}", **headers)
    assert detail_response.status_code == 200
    assert len(detail_response.json()["lines"]) == 1


def test_feasibility_endpoints_are_rbac_protected() -> None:
    """Un role hors du cadrage FEA1-3 (`admin`/`direction`/`resp_production`
    /`resp_commercial`) n'a acces a aucun endpoint `feasibility` — meme
    discipline "deny by default" que le reste du projet (RBAC N2)."""
    tenant = Tenant.objects.create(code="FEA-API2", name="Feasibility API Tenant 2")
    user = User.objects.create_user(
        email="feasibility-outsider@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(user, "magasinier")

    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get("/api/v1/feasibility/studies", **headers)
    assert response.status_code == 403


def test_feasibility_endpoints_require_authentication() -> None:
    client = Client()
    response = client.get("/api/v1/feasibility/studies")
    assert response.status_code == 401
