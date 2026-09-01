"""Menu compte utilisateur (profil/mot de passe/deconnexion) + section
Administration restreinte admin/direction/superutilisateur — chantier
signale par l'utilisateur apres test reel de l'interface : « avoir un menu
pour voir le profil et pour modifier le mot passe ou pour se deconnecter »
et « le menu superadmin ou admin aussi doit etre disponible »."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group
from django.test import Client
from django_otp.oath import totp

from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.services import mfa as mfa_service

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _existing_tenant() -> Tenant:
    # OnboardingMiddleware exige un Tenant deja existant avant tout ecran
    # authentifie normal — meme sequencement que test_mfa_web.py.
    return Tenant.objects.create(code="ACCOUNT-MENU-TEST", name="Test menu compte")


def _logged_in_client(user: User) -> Client:
    client = Client()
    response = client.post("/login/", {"email": user.email, "password": "Str0ngPassw0rd!23"})
    assert response.status_code == 302, response.content
    return client


def _logged_in_admin_client(user: User) -> Client:
    """Complete aussi l'enrolement MFA (role `admin` soumis a MFA
    obligatoire, cf. `settings.CORE_MFA_REQUIRED_ROLES`) — memes
    primitives que `tests/ui/test_all_pages_smoke.py::admin_client`."""
    client = _logged_in_client(user)
    client.get("/mfa/")
    device = mfa_service.enroll_device(user)
    token = str(totp(device.bin_key)).zfill(6)
    response = client.post("/mfa/", {"token": token})
    assert response.status_code == 302, response.content
    return client


@pytest.fixture
def collaborateur_user() -> User:
    user = User.objects.create_user(email="collaborateur@example.com", password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name="collaborateur")
    user.groups.add(group)
    return user


@pytest.fixture
def admin_user() -> User:
    user = User.objects.create_user(email="admin-role@example.com", password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name="admin")
    user.groups.add(group)
    return user


# --- Ecran de profil -------------------------------------------------------


def test_profile_screen_shows_current_values(collaborateur_user: User) -> None:
    collaborateur_user.first_name = "Alice"
    collaborateur_user.phone = "+261340000000"
    collaborateur_user.save(update_fields=["first_name", "phone"])

    client = _logged_in_client(collaborateur_user)
    response = client.get("/profile/")

    assert response.status_code == 200
    assert b"Alice" in response.content
    assert b"+261340000000" in response.content
    assert collaborateur_user.email.encode() in response.content


def test_profile_update_persists_editable_fields(collaborateur_user: User) -> None:
    client = _logged_in_client(collaborateur_user)

    response = client.post(
        "/profile/",
        {
            "first_name": "Bob",
            "last_name": "Rakoto",
            "phone": "+261341111111",
            "preferred_language": "en",
        },
    )
    assert response.status_code == 200
    assert b"Profil mis" in response.content

    collaborateur_user.refresh_from_db()
    assert collaborateur_user.first_name == "Bob"
    assert collaborateur_user.last_name == "Rakoto"
    assert collaborateur_user.phone == "+261341111111"
    assert collaborateur_user.preferred_language == "en"


def test_profile_update_never_changes_email(collaborateur_user: User) -> None:
    original_email = collaborateur_user.email
    client = _logged_in_client(collaborateur_user)

    client.post(
        "/profile/",
        {
            "first_name": "X",
            "last_name": "",
            "phone": "",
            "preferred_language": "fr",
            "email": "hacked@example.com",
        },
    )

    collaborateur_user.refresh_from_db()
    assert collaborateur_user.email == original_email


# --- UXR1 : selecteur de societe active -------------------------------


def test_profile_tenant_switch_accepts_a_real_membership(
    collaborateur_user: User, _existing_tenant: Tenant
) -> None:
    other_tenant = Tenant.objects.create(code="ACCOUNT-MENU-T2", name="Deuxieme societe")
    UserTenantMembership.objects.create(user=collaborateur_user, tenant=other_tenant)
    UserTenantMembership.objects.create(user=collaborateur_user, tenant=_existing_tenant)

    client = _logged_in_client(collaborateur_user)
    response = client.post("/profile/", {"tenant_id": str(other_tenant.id)})
    assert response.status_code == 302

    assert client.session["tenant_id"] == str(other_tenant.id)


def test_profile_tenant_switch_rejects_a_tenant_the_user_is_not_a_member_of(
    collaborateur_user: User,
) -> None:
    foreign_tenant = Tenant.objects.create(code="ACCOUNT-MENU-FOREIGN", name="Societe etrangere")
    # collaborateur_user n'a AUCUNE ligne UserTenantMembership vers foreign_tenant.
    client = _logged_in_client(collaborateur_user)
    original_session_tenant = client.session.get("tenant_id")

    response = client.post("/profile/", {"tenant_id": str(foreign_tenant.id)})
    assert response.status_code == 302

    # jamais positionne : ni le tenant etranger, ni une auto-inscription implicite.
    assert client.session.get("tenant_id") == original_session_tenant
    assert client.session.get("tenant_id") != str(foreign_tenant.id)


def test_profile_screen_offers_only_memberships_of_current_user(
    collaborateur_user: User, _existing_tenant: Tenant
) -> None:
    UserTenantMembership.objects.create(user=collaborateur_user, tenant=_existing_tenant)
    client = _logged_in_client(collaborateur_user)

    response = client.get("/profile/")
    assert response.status_code == 200
    assert _existing_tenant.name.encode() in response.content


# --- Garde admin sur /settings/ --------------------------------------------


def test_settings_hub_refuses_non_admin_role(collaborateur_user: User) -> None:
    client = _logged_in_client(collaborateur_user)
    response = client.get("/settings/")
    assert response.status_code == 403


def test_settings_hub_allows_admin_role(admin_user: User) -> None:
    client = _logged_in_admin_client(admin_user)
    response = client.get("/settings/")
    assert response.status_code == 200


def test_settings_hub_allows_superuser_without_admin_group() -> None:
    user = User.objects.create_superuser(email="super@example.com", password="Str0ngPassw0rd!23")
    client = _logged_in_admin_client(user)
    response = client.get("/settings/")
    assert response.status_code == 200


# --- Menu topbar ------------------------------------------------------------


def test_account_menu_present_for_any_authenticated_user(collaborateur_user: User) -> None:
    client = _logged_in_client(collaborateur_user)
    response = client.get("/dashboard/")
    assert response.status_code == 200
    assert b"account-menu" in response.content
    assert b"Voir le profil" in response.content
    assert b"Modifier le mot de passe" in response.content
    assert "Se déconnecter".encode() in response.content


def test_administration_link_hidden_for_non_admin_role(collaborateur_user: User) -> None:
    client = _logged_in_client(collaborateur_user)
    response = client.get("/dashboard/")
    assert response.status_code == 200
    assert b"Administration" not in response.content


def test_administration_link_visible_for_admin_role(admin_user: User) -> None:
    client = _logged_in_admin_client(admin_user)
    response = client.get("/dashboard/")
    assert response.status_code == 200
    assert b"Administration" in response.content
