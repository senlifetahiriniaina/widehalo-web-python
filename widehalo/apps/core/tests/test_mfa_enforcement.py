from __future__ import annotations

import pytest
from django.contrib.auth.models import Group
from django.test import Client

from apps.core.models.user import User
from apps.core.services import mfa as mfa_service

pytestmark = pytest.mark.django_db


@pytest.fixture
def comptable_user() -> User:
    user = User.objects.create_user(email="comptable@example.com", password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name="comptable")
    user.groups.add(group)
    return user


def test_mfa_required_role_without_device_gets_enrollment_required(comptable_user: User) -> None:
    client = Client()
    response = client.post(
        "/api/v1/auth/login",
        {"email": comptable_user.email, "password": "Str0ngPassw0rd!23"},
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "mfa_enrollment_required"
    assert body["access"] is None


def test_mfa_required_role_with_confirmed_device_gets_mfa_required(comptable_user: User) -> None:
    device = mfa_service.enroll_device(comptable_user)
    device.confirmed = True
    device.save(update_fields=["confirmed"])

    client = Client()
    response = client.post(
        "/api/v1/auth/login",
        {"email": comptable_user.email, "password": "Str0ngPassw0rd!23"},
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json()["status"] == "mfa_required"


def test_mfa_verify_with_correct_totp_completes_login(comptable_user: User) -> None:
    device = mfa_service.enroll_device(comptable_user)
    device.confirmed = True
    device.save(update_fields=["confirmed"])

    from django_otp.oath import totp

    token = str(totp(device.bin_key)).zfill(6)

    client = Client()
    response = client.post(
        "/api/v1/auth/mfa/verify",
        {"email": comptable_user.email, "token": token},
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["access"]


def test_role_without_mfa_requirement_is_not_gated(db) -> None:
    user = User.objects.create_user(
        email="collaborateur2@example.com", password="Str0ngPassw0rd!23"
    )
    assert mfa_service.mfa_required_for_user(user) is False
