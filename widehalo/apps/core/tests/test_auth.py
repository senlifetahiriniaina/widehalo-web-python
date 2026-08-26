from __future__ import annotations

import pytest
from django.test import Client

from apps.core.models.user import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def user() -> User:
    return User.objects.create_user(email="collaborateur@example.com", password="Str0ngPassw0rd!23")


def test_login_returns_tokens_for_role_without_mfa(user: User) -> None:
    client = Client()
    response = client.post(
        "/api/v1/auth/login",
        {"email": user.email, "password": "Str0ngPassw0rd!23"},
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["access"]
    assert body["refresh"]


def test_login_rejects_invalid_credentials(user: User) -> None:
    client = Client()
    response = client.post(
        "/api/v1/auth/login",
        {"email": user.email, "password": "wrong-password"},
        content_type="application/json",
    )
    assert response.status_code == 401


def test_five_failed_logins_lock_the_account(user: User) -> None:
    client = Client()
    for _ in range(5):
        client.post(
            "/api/v1/auth/login",
            {"email": user.email, "password": "wrong-password"},
            content_type="application/json",
        )
    response = client.post(
        "/api/v1/auth/login",
        {"email": user.email, "password": "Str0ngPassw0rd!23"},
        content_type="application/json",
    )
    # django-axes verrouille au niveau middleware (429), meme avec le bon
    # mot de passe, tant que le cooloff n'est pas ecoule.
    assert response.status_code == 429


def test_password_below_minimum_length_is_rejected() -> None:
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        validate_password("short1!")


def test_compromised_password_is_rejected() -> None:
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        validate_password("motdepasse123")
