from __future__ import annotations

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db


def test_english_accept_language_translates_error_message() -> None:
    client = Client()
    response = client.post(
        "/api/v1/auth/mfa/enroll",
        {"email": "inconnu@example.com", "token": "000000"},
        content_type="application/json",
        HTTP_ACCEPT_LANGUAGE="en",
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "user not found"


def test_french_is_the_default_language() -> None:
    client = Client()
    response = client.post(
        "/api/v1/auth/mfa/enroll",
        {"email": "inconnu@example.com", "token": "000000"},
        content_type="application/json",
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "utilisateur introuvable"


def test_french_accept_language_is_explicit_too() -> None:
    client = Client()
    response = client.post(
        "/api/v1/auth/mfa/enroll",
        {"email": "inconnu@example.com", "token": "000000"},
        content_type="application/json",
        HTTP_ACCEPT_LANGUAGE="fr",
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "utilisateur introuvable"


def test_mga_format_filter() -> None:
    from decimal import Decimal

    from apps.core.utils.formatting import format_mga

    # Espace insecable (convention typographique francaise pour les milliers).
    nbsp = "\N{NO-BREAK SPACE}"
    assert format_mga(Decimal("1234567.8901")) == f"1{nbsp}234{nbsp}568{nbsp}Ar"
