from __future__ import annotations

import pytest
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.test import Client
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.core.models.user import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def user() -> User:
    return User.objects.create_user(email="reset@example.com", password="Str0ngPassw0rd!23")


def test_password_reset_confirm_with_valid_token_changes_password(user: User) -> None:
    client = Client()
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = PasswordResetTokenGenerator().make_token(user)

    response = client.post(
        "/api/v1/auth/password-reset/confirm",
        {"uid": uid, "token": token, "new_password": "AnotherStr0ngPassw0rd!45"},
        content_type="application/json",
    )
    assert response.status_code == 200

    login_response = client.post(
        "/api/v1/auth/login",
        {"email": user.email, "password": "AnotherStr0ngPassw0rd!45"},
        content_type="application/json",
    )
    assert login_response.json()["status"] == "ok"


def test_password_reset_confirm_with_invalid_token_is_rejected(user: User) -> None:
    client = Client()
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    response = client.post(
        "/api/v1/auth/password-reset/confirm",
        {"uid": uid, "token": "invalid-token", "new_password": "AnotherStr0ngPassw0rd!45"},
        content_type="application/json",
    )
    assert response.status_code == 400


def test_password_reset_request_does_not_leak_user_existence() -> None:
    client = Client()
    response = client.post(
        "/api/v1/auth/password-reset/request",
        {"email": "unknown@example.com"},
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_refresh_rotates_token_and_blacklists_the_old_one(user: User) -> None:
    client = Client()
    login_response = client.post(
        "/api/v1/auth/login",
        {"email": user.email, "password": "Str0ngPassw0rd!23"},
        content_type="application/json",
    )
    refresh_token = login_response.json()["refresh"]

    refresh_response = client.post(
        "/api/v1/auth/refresh", {"refresh": refresh_token}, content_type="application/json"
    )
    assert refresh_response.status_code == 200
    new_refresh = refresh_response.json()["refresh"]
    assert new_refresh != refresh_token

    # Le refresh token original est blackliste (rotation) : le reutiliser doit echouer.
    reuse_response = client.post(
        "/api/v1/auth/refresh", {"refresh": refresh_token}, content_type="application/json"
    )
    assert reuse_response.status_code == 500 or reuse_response.status_code >= 400


def test_logout_blacklists_refresh_token(user: User) -> None:
    client = Client()
    login_response = client.post(
        "/api/v1/auth/login",
        {"email": user.email, "password": "Str0ngPassw0rd!23"},
        content_type="application/json",
    )
    refresh_token = login_response.json()["refresh"]

    logout_response = client.post(
        "/api/v1/auth/logout", {"refresh": refresh_token}, content_type="application/json"
    )
    assert logout_response.status_code == 200

    reuse_response = client.post(
        "/api/v1/auth/refresh", {"refresh": refresh_token}, content_type="application/json"
    )
    assert reuse_response.status_code >= 400
