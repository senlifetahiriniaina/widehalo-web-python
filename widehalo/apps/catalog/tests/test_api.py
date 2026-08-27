from __future__ import annotations

import pytest
from django.test import Client

from apps.catalog.models import UnitOfMeasure
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


def test_create_template_and_read_default_price_via_api() -> None:
    tenant = Tenant.objects.create(code="CAT-API", name="Catalog API Tenant")
    user = User.objects.create_user(email="cat-api@example.com", password="Str0ngPassw0rd!23")
    # "acheteur" (view+add+change sur catalog, cf. ROLE_APP_PERMISSIONS)
    # n'est pas dans settings.CORE_MFA_REQUIRED_ROLES ({"admin", "direction",
    # "comptable", "rh"}), contrairement a "admin" — indispensable ici car un
    # login MFA-gated renvoie mfa_enrollment_required (access=None), pas un
    # vrai JWT, ce qui ferait echouer la requete en 401 avant meme d'atteindre
    # la verification RBAC.
    grant_role(user, "acheteur")
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


def test_create_template_without_permission_is_forbidden() -> None:
    """Regression T6/RBAC : require_permission("catalog.add_producttemplate")
    doit refuser (403) un utilisateur authentifie qui n'a que la lecture.
    "chef_atelier" a uniquement "view" sur catalog (ROLE_APP_PERMISSIONS) et
    n'est pas dans CORE_MFA_REQUIRED_ROLES ("rh", le seul role sans AUCUN
    acces catalog, y est en revanche — son login renverrait
    mfa_enrollment_required au lieu d'un JWT exploitable, faussant ce test).
    """
    tenant = Tenant.objects.create(code="CAT-API-DENY", name="Catalog API Deny Tenant")
    user = User.objects.create_user(email="cat-api-deny@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "chef_atelier")

    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": str(tenant.id)}

    # "view" reste autorise : seule l'ecriture (add) doit etre refusee.
    list_response = client.get("/api/v1/catalog/templates", **headers)
    assert list_response.status_code == 200

    create_response = client.post(
        "/api/v1/catalog/templates",
        {"name": "Pantalon", "base_uom_id": "00000000-0000-0000-0000-000000000000"},
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 403
