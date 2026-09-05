"""L0-4 — ecran d'exploitation de l'ordonnanceur
(`apps.core.views.scheduling`) : garde `is_superuser` STRICT (jamais
`admin`/`direction` seuls, les planifications etant globales a l'instance),
et surtout **visibilite du defaut d'origine** — une commande declaree mais
non planifiee doit se voir, pas se deduire."""

from __future__ import annotations

import pytest
from django.test import Client
from django_otp.oath import totp

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services import mfa as mfa_service
from apps.core.services.scheduled_commands import list_scheduled_commands
from apps.core.tests.utils import grant_role

pytestmark = pytest.mark.django_db

URL = "/settings/scheduled-commands/"


def _logged_in_client(user: User, tenant: Tenant) -> Client:
    client = Client()
    response = client.post("/login/", {"email": user.email, "password": "Str0ngPassw0rd!23"})
    assert response.status_code == 302, response.content
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    client.get("/mfa/")
    device = mfa_service.enroll_device(user)
    token = str(totp(device.bin_key)).zfill(6)
    assert client.post("/mfa/", {"token": token}).status_code == 302
    return client


def test_admin_role_non_superuser_is_refused() -> None:
    tenant = Tenant.objects.create(code="SCHED-DENY", name="Sched Deny")
    user = User.objects.create_user(email="sched-deny@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "admin")
    client = _logged_in_client(user, tenant)

    assert client.get(URL).status_code == 403


def test_superuser_sees_every_declared_command() -> None:
    tenant = Tenant.objects.create(code="SCHED-OK", name="Sched OK")
    user = User.objects.create_superuser(email="sched-ok@example.com", password="Str0ngPassw0rd!23")
    client = _logged_in_client(user, tenant)

    response = client.get(URL)
    assert response.status_code == 200
    body = response.content.decode()
    for entry in list_scheduled_commands():
        assert entry.command in body, f"{entry.command} absente de l'ecran."


def test_a_declared_but_unsynchronised_command_is_flagged() -> None:
    """Sans cette alerte, une commande ajoutee par une livraison et jamais
    synchronisee resterait inerte exactement comme les dix-neuf d'origine —
    juste, declaree, et jamais executee."""
    tenant = Tenant.objects.create(code="SCHED-WARN", name="Sched Warn")
    user = User.objects.create_superuser(
        email="sched-warn@example.com", password="Str0ngPassw0rd!23"
    )
    client = _logged_in_client(user, tenant)

    # Aucune synchronisation n'a eu lieu : toutes les commandes declarees
    # sont donc non planifiees.
    response = client.get(URL)
    assert "Non planifiée" in response.content.decode()


def test_the_alert_disappears_once_synchronised() -> None:
    from apps.core.tasks import sync_schedules

    sync_schedules()
    tenant = Tenant.objects.create(code="SCHED-SYNC", name="Sched Sync")
    user = User.objects.create_superuser(
        email="sched-sync@example.com", password="Str0ngPassw0rd!23"
    )
    client = _logged_in_client(user, tenant)

    body = client.get(URL).content.decode()
    assert "Non planifiée" not in body
