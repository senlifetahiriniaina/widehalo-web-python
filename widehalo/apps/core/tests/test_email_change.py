"""UXR1 — `apps.core.services.email_change` : confirmation d'un changement
d'e-mail par lien a jeton, meme discipline de rejet indiscernable que
`apps.projects.services.guest_portal.resolve_guest_access` (cf. sa
docstring, et `apps.projects.tests.test_guest_portal` pour le meme genre de
couverture sur le mecanisme jumeau)."""

from __future__ import annotations

import datetime as dt

import pytest
from django.core import mail
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.email_change import confirm_email_change, request_email_change
from apps.core.tests.factories import (
    TenantFactory,
    UserEmailChangeRequestFactory,
    UserFactory,
    UserTenantMembershipFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant() -> Tenant:
    return TenantFactory()


# --- request_email_change -------------------------------------------------


def test_request_email_change_creates_row_and_sends_email(tenant: Tenant) -> None:
    user = UserFactory(email="old@example.com")
    admin = UserFactory(email="admin@example.com")
    UserTenantMembershipFactory(user=admin, tenant=tenant)

    mail.outbox.clear()
    change_request = request_email_change(user, "new@example.com", requested_by=admin)

    assert change_request.new_email == "new@example.com"
    assert change_request.requested_by_id == admin.id
    assert change_request.confirmed_at is None
    assert change_request.plaintext_token
    user.refresh_from_db()
    assert user.email == "old@example.com"  # jamais ecrit avant confirmation

    assert len(mail.outbox) == 1
    sent = mail.outbox[0]
    assert sent.to == ["new@example.com"]
    assert change_request.plaintext_token in sent.body


def test_request_email_change_self_service_has_no_requested_by(tenant: Tenant) -> None:
    """`requested_by=None` : cas ou l'utilisateur change lui-meme son
    e-mail (cf. docstring de `UserEmailChangeRequest`)."""
    user = UserFactory(email="old2@example.com")
    UserTenantMembershipFactory(user=user, tenant=tenant)

    change_request = request_email_change(user, "new2@example.com", requested_by=None)

    assert change_request.requested_by_id is None


# --- confirm_email_change : succes ----------------------------------------


def test_confirm_email_change_with_valid_token_changes_email() -> None:
    user = UserFactory(email="before@example.com")
    change_request = UserEmailChangeRequestFactory(user=user, new_email="after@example.com")

    result = confirm_email_change(change_request.plaintext_token)

    assert result is True
    user.refresh_from_db()
    assert user.email == "after@example.com"
    change_request.refresh_from_db()
    assert change_request.confirmed_at is not None


# --- confirm_email_change : rejet indiscernable ----------------------------


def test_confirm_email_change_unknown_token_fails() -> None:
    assert confirm_email_change("token-inexistant") is False


def test_confirm_email_change_empty_token_fails() -> None:
    assert confirm_email_change("") is False


def test_confirm_email_change_expired_token_fails() -> None:
    user = UserFactory(email="expired@example.com")
    change_request = UserEmailChangeRequestFactory(
        user=user,
        new_email="wont-apply@example.com",
        expires_at=dt.datetime(2020, 1, 1, tzinfo=dt.UTC),
    )

    assert confirm_email_change(change_request.plaintext_token) is False
    user.refresh_from_db()
    assert user.email == "expired@example.com"


def test_confirm_email_change_already_confirmed_token_fails() -> None:
    user = UserFactory(email="already@example.com")
    change_request = UserEmailChangeRequestFactory(
        user=user, new_email="second-attempt@example.com"
    )
    assert confirm_email_change(change_request.plaintext_token) is True
    user.refresh_from_db()
    assert user.email == "second-attempt@example.com"

    # Un second appel avec le MEME token (deja confirme) echoue — l'e-mail
    # ne change plus, meme si un nouvel appelant tentait de rejouer le lien.
    assert confirm_email_change(change_request.plaintext_token) is False


def test_confirm_email_change_three_failure_cases_are_indistinguishable() -> None:
    """Les 3 cas d'echec (inconnu / deja confirme / expire) renvoient
    exactement `False`, sans exception ni signal permettant de les
    distinguer cote appelant — meme verification que
    `test_guest_portal.py` pour le mecanisme jumeau."""
    unknown_result = confirm_email_change("does-not-exist")

    confirmed = UserEmailChangeRequestFactory(user=UserFactory())
    confirm_email_change(confirmed.plaintext_token)
    already_confirmed_result = confirm_email_change(confirmed.plaintext_token)

    expired = UserEmailChangeRequestFactory(
        user=UserFactory(), expires_at=dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
    )
    expired_result = confirm_email_change(expired.plaintext_token)

    assert unknown_result is already_confirmed_result is expired_result is False


# --- Vue publique GET /account/confirm-email/<token>/ ----------------------


def test_confirm_email_view_is_public_and_does_not_require_login() -> None:
    user = User.objects.create_user(email="public1@example.com", password="Str0ngPassw0rd!23")
    change_request = UserEmailChangeRequestFactory(user=user, new_email="public2@example.com")

    client = Client()  # jamais de connexion prealable
    response = client.get(f"/account/confirm-email/{change_request.plaintext_token}/")

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.email == "public2@example.com"


def test_confirm_email_view_renders_generic_failure_for_bad_token() -> None:
    client = Client()
    response = client.get("/account/confirm-email/not-a-real-token/")
    assert response.status_code == 200
    assert b"invalide" in response.content.lower() or b"Lien invalide" in response.content
