"""UXR1 — ecran admin de gestion des utilisateurs
(`apps.core.views.admin_users`) : garde RBAC (`core.manage_users`), edition
roles/societes, et delegation du changement d'e-mail a `services/
email_change.py` (jamais une ecriture directe)."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group
from django.core import mail
from django.test import Client
from django_otp.oath import totp

from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserEmailChangeRequest, UserTenantMembership
from apps.core.services import mfa as mfa_service
from apps.core.tests.utils import grant_role

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _existing_tenant() -> Tenant:
    # OnboardingMiddleware exige un Tenant deja existant avant tout ecran
    # authentifie normal (meme sequencement que test_account_menu.py).
    return Tenant.objects.create(code="ADMIN-USERS-T1", name="Test admin utilisateurs")


def _logged_in_client(user: User) -> Client:
    client = Client()
    response = client.post("/login/", {"email": user.email, "password": "Str0ngPassw0rd!23"})
    assert response.status_code == 302, response.content
    return client


def _logged_in_admin_client(user: User) -> Client:
    """`admin`/`direction` sont soumis a MFA obligatoire
    (`settings.CORE_MFA_REQUIRED_ROLES`) — complete l'enrolement, meme
    primitives que `test_account_menu.py::_logged_in_admin_client`."""
    client = _logged_in_client(user)
    client.get("/mfa/")
    device = mfa_service.enroll_device(user)
    token = str(totp(device.bin_key)).zfill(6)
    response = client.post("/mfa/", {"token": token})
    assert response.status_code == 302, response.content
    return client


@pytest.fixture
def admin_user() -> User:
    user = User.objects.create_user(email="admin-users@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "admin")
    return user


@pytest.fixture
def collaborateur_user() -> User:
    user = User.objects.create_user(
        email="collab-admin-users@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(user, "collaborateur")
    return user


@pytest.fixture
def target_user() -> User:
    return User.objects.create_user(email="target-user@example.com", password="Str0ngPassw0rd!23")


# --- Garde RBAC --------------------------------------------------------


def test_admin_user_list_refuses_role_without_manage_users(collaborateur_user: User) -> None:
    client = _logged_in_client(collaborateur_user)
    response = client.get("/users/")
    assert response.status_code == 403


def test_admin_user_edit_refuses_role_without_manage_users(
    collaborateur_user: User, target_user: User
) -> None:
    client = _logged_in_client(collaborateur_user)
    response = client.get(f"/users/{target_user.id}/edit/")
    assert response.status_code == 403


def test_admin_user_list_allows_admin_role(admin_user: User) -> None:
    client = _logged_in_admin_client(admin_user)
    response = client.get("/users/")
    assert response.status_code == 200


# --- Edition roles/societes ---------------------------------------------


def test_admin_can_edit_roles_and_tenant_memberships(admin_user: User, target_user: User) -> None:
    other_tenant = Tenant.objects.create(code="ADMIN-USERS-T2", name="Autre societe")
    role_a, _ = Group.objects.get_or_create(name="comptable")
    role_b, _ = Group.objects.get_or_create(name="rh")
    target_user.groups.add(role_a)

    client = _logged_in_admin_client(admin_user)
    response = client.post(
        f"/users/{target_user.id}/edit/",
        {
            "email": target_user.email,
            "first_name": "Rindra",
            "last_name": "Rakoto",
            "phone": "+261340000001",
            "preferred_language": "en",
            "groups": [str(role_b.id)],
            "tenants": [str(other_tenant.id)],
        },
    )
    assert response.status_code == 302, response.content

    target_user.refresh_from_db()
    assert target_user.first_name == "Rindra"
    assert target_user.preferred_language == "en"
    assert set(target_user.groups.values_list("name", flat=True)) == {"rh"}
    assert set(
        UserTenantMembership.objects.filter(user=target_user).values_list("tenant_id", flat=True)
    ) == {other_tenant.id}


def test_admin_edit_screen_preferred_language_is_a_real_select(
    admin_user: User, target_user: User
) -> None:
    client = _logged_in_admin_client(admin_user)
    response = client.get(f"/users/{target_user.id}/edit/")
    assert response.status_code == 200
    assert b'<select id="preferred_language" name="preferred_language">' in response.content
    assert b"Fran\xc3\xa7ais" in response.content or "Français".encode() in response.content
    assert b"English" in response.content


# --- Changement d'e-mail -------------------------------------------------


def test_admin_changing_email_creates_request_and_never_writes_directly(
    admin_user: User, target_user: User
) -> None:
    original_email = target_user.email
    UserTenantMembership.objects.create(user=admin_user, tenant=Tenant.objects.first())

    client = _logged_in_admin_client(admin_user)
    mail.outbox.clear()
    response = client.post(
        f"/users/{target_user.id}/edit/",
        {
            "email": "nouvelle-adresse@example.com",
            "first_name": "",
            "last_name": "",
            "phone": "",
            "preferred_language": "fr",
        },
    )
    assert response.status_code == 302, response.content
    assert "email_change_pending=1" in response.url

    target_user.refresh_from_db()
    assert target_user.email == original_email  # jamais ecrit directement

    change_request = UserEmailChangeRequest.all_objects.get(user=target_user)
    assert change_request.new_email == "nouvelle-adresse@example.com"
    assert change_request.requested_by_id == admin_user.id
    assert change_request.confirmed_at is None

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["nouvelle-adresse@example.com"]

    follow_up = client.get(response.url)
    assert follow_up.status_code == 200
    assert b"confirmation" in follow_up.content.lower()
