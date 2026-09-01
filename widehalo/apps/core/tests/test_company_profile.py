"""Ecran "Profil de l'entreprise" (chantier marque d'entreprise sur le PDF
devis/commande) : RBAC (memes garde/roles qu'`apps.core.views.pages.
settings_page`), upload de logo + edition adresse/telephone/e-mail, et
`apps.core.services.branding.get_tenant_logo_data_uri`."""

from __future__ import annotations

import base64

import pytest
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django_otp.oath import totp

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services import mfa as mfa_service
from apps.core.services.branding import get_tenant_logo_data_uri
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db

# PNG 1x1 minimal valide (memes octets que ceux deja utilises par d'autres
# suites de ce depot pour un upload d'image de test).
_PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _logged_in_client(user: User, tenant: Tenant) -> Client:
    client = Client()
    response = client.post("/login/", {"email": user.email, "password": "Str0ngPassw0rd!23"})
    assert response.status_code == 302, response.content
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def _complete_mfa(client: Client, user: User) -> None:
    client.get("/mfa/")
    device = mfa_service.enroll_device(user)
    token = str(totp(device.bin_key)).zfill(6)
    response = client.post("/mfa/", {"token": token})
    assert response.status_code == 302, response.content


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(code="COMPANY-PROFILE", name="Test profil entreprise")


@pytest.fixture
def admin_client(tenant: Tenant) -> Client:
    user = User.objects.create_user(email="admin-profile@example.com", password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name="admin")
    user.groups.add(group)
    client = _logged_in_client(user, tenant)
    _complete_mfa(client, user)
    return client


def test_company_profile_refuses_non_admin_role(tenant: Tenant) -> None:
    user = User.objects.create_user(email="collab-profile@example.com", password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name="collaborateur")
    user.groups.add(group)
    client = _logged_in_client(user, tenant)

    response = client.get("/settings/company-profile/")
    assert response.status_code == 403


def test_company_profile_allows_admin_role(admin_client: Client) -> None:
    response = admin_client.get("/settings/company-profile/")
    assert response.status_code == 200


def test_company_profile_allows_superuser_without_admin_group(tenant: Tenant) -> None:
    user = User.objects.create_superuser(email="super-profile@example.com", password="Str0ngPassw0rd!23")
    client = _logged_in_client(user, tenant)
    _complete_mfa(client, user)

    response = client.get("/settings/company-profile/")
    assert response.status_code == 200


def test_company_profile_updates_address_phone_email(admin_client: Client, tenant: Tenant) -> None:
    response = admin_client.post(
        "/settings/company-profile/",
        {"address": "Lot II M 12 Antananarivo", "phone": "+261 34 00 000 00", "email": "contact@example.com"},
    )
    assert response.status_code == 302

    with use_tenant(tenant.id):
        tenant.refresh_from_db()
    assert tenant.address == "Lot II M 12 Antananarivo"
    assert tenant.phone == "+261 34 00 000 00"
    assert tenant.email == "contact@example.com"


def test_company_profile_uploads_logo(admin_client: Client, tenant: Tenant) -> None:
    logo = SimpleUploadedFile("logo.png", _PNG_1PX, content_type="image/png")
    response = admin_client.post(
        "/settings/company-profile/",
        {"address": "", "phone": "", "email": "", "logo": logo},
    )
    assert response.status_code == 302

    with use_tenant(tenant.id):
        tenant.refresh_from_db()
    assert tenant.logo
    data_uri = get_tenant_logo_data_uri(tenant)
    assert data_uri is not None
    assert data_uri.startswith("data:image/png;base64,")


def test_get_tenant_logo_data_uri_returns_none_without_logo(tenant: Tenant) -> None:
    assert get_tenant_logo_data_uri(tenant) is None
