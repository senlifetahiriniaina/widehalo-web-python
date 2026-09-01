"""Ecrans de sauvegarde/restauration/reinitialisation (BKP5,
`apps.core.views.backup_admin`) : garde `is_superuser` STRICT (jamais
`admin`/`direction` seuls), presence du champ de confirmation stricte
(type-to-confirm), accessibilite de base (labels sur tout champ)."""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup
from django.test import Client
from django_otp.oath import totp

from apps.core.models.backup import TenantBackupSchedule
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services import mfa as mfa_service
from apps.core.tests.utils import grant_role

pytestmark = pytest.mark.django_db


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


def _superuser_client(tenant: Tenant, email: str) -> Client:
    user = User.objects.create_superuser(email=email, password="Str0ngPassw0rd!23")
    client = _logged_in_client(user, tenant)
    _complete_mfa(client, user)
    return client


def _assert_all_fields_labelled(soup: BeautifulSoup, screen: str) -> None:
    labelled_ids = {label.get("for") for label in soup.find_all("label") if label.get("for")}
    for field in soup.find_all(["input", "select", "textarea"]):
        if field.get("type") in {"hidden", "csrfmiddlewaretoken"}:
            continue
        wrapped_by_label = field.find_parent("label") is not None
        assert field.get("id") in labelled_ids or field.get("aria-label") or wrapped_by_label, (
            f"[{screen}] champ sans label associe : {field}"
        )


def test_admin_role_non_superuser_gets_403_on_every_backup_screen() -> None:
    tenant = Tenant.objects.create(code="BKUI-DENY", name="Backup UI Deny")
    user = User.objects.create_user(email="bkui-deny@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "admin")
    client = _logged_in_client(user, tenant)
    _complete_mfa(client, user)

    assert client.get("/backups/").status_code == 403
    assert client.get("/backups/schedule/").status_code == 403
    assert client.get("/backups/reset/").status_code == 403


def test_backup_list_screen_renders_for_superuser() -> None:
    tenant = Tenant.objects.create(code="BKUI-LIST", name="Backup UI List")
    client = _superuser_client(tenant, "bkui-list@example.com")

    response = client.get("/backups/")
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    _assert_all_fields_labelled(soup, "backup_list")
    # Champ de confirmation stricte (type-to-confirm) present sur le
    # formulaire de restauration de cet ecran.
    assert soup.find("input", {"name": "confirm"}) is not None


def test_reset_screen_renders_with_strict_confirmation_field() -> None:
    tenant = Tenant.objects.create(code="BKUI-RESET", name="Backup UI Reset")
    client = _superuser_client(tenant, "bkui-reset@example.com")

    response = client.get("/backups/reset/")
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    _assert_all_fields_labelled(soup, "reset_company_data")
    confirm_field = soup.find("input", {"name": "confirm"})
    assert confirm_field is not None
    assert confirm_field.get("required") is not None


def test_schedule_screen_renders_and_updates() -> None:
    tenant = Tenant.objects.create(code="BKUI-SCHED", name="Backup UI Schedule")
    client = _superuser_client(tenant, "bkui-sched@example.com")

    response = client.get("/backups/schedule/")
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    _assert_all_fields_labelled(soup, "backup_schedule")

    update = client.post("/backups/schedule/", {"frequency": "weekly", "retention_count": "4"})
    assert update.status_code == 302
    schedule = TenantBackupSchedule.all_objects.get(tenant=tenant)
    assert schedule.frequency == "weekly"
    assert schedule.retention_count == 4


def test_settings_hub_card_only_shown_to_superuser() -> None:
    tenant = Tenant.objects.create(code="BKUI-CARD", name="Backup UI Card")
    admin_user = User.objects.create_user(
        email="bkui-card-admin@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(admin_user, "admin")
    admin_client = _logged_in_client(admin_user, tenant)
    _complete_mfa(admin_client, admin_user)
    admin_response = admin_client.get("/settings/")
    assert admin_response.status_code == 200
    assert b"backups/" not in admin_response.content

    superuser_client = _superuser_client(tenant, "bkui-card-super@example.com")
    superuser_response = superuser_client.get("/settings/")
    assert superuser_response.status_code == 200
    assert b"backups/" in superuser_response.content
