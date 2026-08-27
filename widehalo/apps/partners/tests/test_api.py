from __future__ import annotations

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


def test_create_and_list_partners_via_api() -> None:
    tenant = Tenant.objects.create(code="PART-API", name="Partners API Tenant")
    user = User.objects.create_user(email="part-api@example.com", password="Str0ngPassw0rd!23")
    # "commercial" (view+add+change sur partners, cf. ROLE_APP_PERMISSIONS)
    # n'est pas dans settings.CORE_MFA_REQUIRED_ROLES ({"admin", "direction",
    # "comptable", "rh"}), contrairement a "admin" — indispensable ici car un
    # login MFA-gated renvoie mfa_enrollment_required (access=None), pas un
    # vrai JWT, ce qui ferait echouer la requete en 401 avant meme d'atteindre
    # la verification RBAC.
    grant_role(user, "commercial")
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


def test_list_partners_without_role_is_forbidden() -> None:
    tenant = Tenant.objects.create(code="PART-API-DENY", name="Partners API Deny Tenant")
    user = User.objects.create_user(email="part-api-deny@example.com", password="Str0ngPassw0rd!23")
    # "chef_atelier" n'a aucune entree "partners" dans ROLE_APP_PERMISSIONS
    # (donc aucune permission sur ce module) et n'est pas dans
    # CORE_MFA_REQUIRED_ROLES ("rh", qui n'a pas non plus d'acces partners,
    # y est en revanche — son login renverrait mfa_enrollment_required au
    # lieu d'un JWT exploitable, faussant ce test de regression 403).
    grant_role(user, "chef_atelier")
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": str(tenant.id)}

    list_response = client.get("/api/v1/partners", **headers)
    assert list_response.status_code == 403

    create_response = client.post(
        "/api/v1/partners",
        {"name": "Textile Import Export", "roles": ["client"], "nif": "NIF-API-2"},
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 403
