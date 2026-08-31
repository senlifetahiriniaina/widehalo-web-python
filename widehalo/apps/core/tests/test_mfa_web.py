"""Ecran web MFA (`/mfa/`) — regression sur le bug reel corrige : la vue
n'existait pas du tout avant ce correctif, `MFAEnforcementMiddleware`
redirigeait vers une 404 des la premiere connexion web d'un compte soumis
a MFA obligatoire (cf. docstring de `apps.core.views.auth_web.mfa_view`)."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group
from django.test import Client
from django_otp.oath import totp

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services import mfa as mfa_service

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _existing_tenant() -> Tenant:
    # OnboardingMiddleware s'execute AVANT MFAEnforcementMiddleware et force
    # /setup/ tant qu'aucun Tenant n'existe (controle global, pas par
    # utilisateur) — sans celui-ci, /mfa/ n'est jamais atteint dans ces
    # tests, exactement le meme sequencement que le parcours reel de
    # l'utilisateur (creer la premiere societe PUIS se heurter au MFA).
    return Tenant.objects.create(code="MFA-WEB-TEST", name="Test MFA web")


@pytest.fixture
def comptable_user() -> User:
    user = User.objects.create_user(email="mfa-web@example.com", password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name="comptable")
    user.groups.add(group)
    return user


def _logged_in_client(user: User) -> Client:
    # `Client.login()` appelle `authenticate()` sans `request`, or
    # `AxesBackend` l'exige (cf. apps/core/tests/test_mfa_enforcement.py,
    # meme contrainte) — passer par la vraie vue de connexion web a la
    # place, seule facon realiste de peupler la session comme un vrai
    # navigateur.
    client = Client()
    response = client.post("/login/", {"email": user.email, "password": "Str0ngPassw0rd!23"})
    assert response.status_code == 302, response.content
    return client


def test_mfa_url_resolves_and_is_not_a_404(comptable_user: User) -> None:
    client = _logged_in_client(comptable_user)
    response = client.get("/mfa/")
    assert response.status_code == 200


def test_enrollment_screen_shows_qr_code_for_user_without_device(
    comptable_user: User,
) -> None:
    client = _logged_in_client(comptable_user)
    response = client.get("/mfa/")
    assert response.status_code == 200
    assert b"data:image/png;base64," in response.content


def test_enrollment_with_correct_token_verifies_session_and_redirects(
    comptable_user: User,
) -> None:
    client = _logged_in_client(comptable_user)
    client.get("/mfa/")  # cree le device non confirme, comme /api/v1/auth/mfa/enroll

    device = mfa_service.enroll_device(comptable_user)
    token = str(totp(device.bin_key)).zfill(6)

    response = client.post("/mfa/", {"token": token})
    assert response.status_code == 302
    assert response.url == "/dashboard/"

    device.refresh_from_db()
    assert device.confirmed is True

    # La session est bien verifiee : un GET ulterieur ne redemande plus MFA.
    response = client.get("/mfa/")
    assert response.status_code == 302
    assert response.url == "/dashboard/"


def test_enrollment_with_wrong_token_shows_error_without_confirming(
    comptable_user: User,
) -> None:
    client = _logged_in_client(comptable_user)
    response = client.post("/mfa/", {"token": "000000"})
    assert response.status_code == 200
    assert b"Code invalide" in response.content

    device = mfa_service.enroll_device(comptable_user)
    assert device.confirmed is False


def test_verification_screen_for_already_confirmed_device(comptable_user: User) -> None:
    device = mfa_service.enroll_device(comptable_user)
    device.confirmed = True
    device.save(update_fields=["confirmed"])

    client = _logged_in_client(comptable_user)
    response = client.get("/mfa/")
    assert response.status_code == 200
    assert b"data:image/png;base64," not in response.content  # pas de re-enrolement

    token = str(totp(device.bin_key)).zfill(6)
    response = client.post("/mfa/", {"token": token})
    assert response.status_code == 302
    assert response.url == "/dashboard/"


def test_user_without_mfa_requirement_is_redirected_away_from_mfa_screen() -> None:
    user = User.objects.create_user(email="no-mfa@example.com", password="Str0ngPassw0rd!23")
    client = _logged_in_client(user)
    response = client.get("/mfa/")
    assert response.status_code == 302
    assert response.url == "/dashboard/"
