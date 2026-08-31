"""Test leger de `seed_core` (T10) : verifie que la commande cree le tenant
demo, les 11 roles et les 3 utilisateurs demo attendus, et que la relancer
ne duplique rien."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command

from apps.core.models.tenant import Tenant
from apps.core.models.user import User

pytestmark = pytest.mark.django_db


def test_seed_core_creates_demo_tenant_roles_and_users() -> None:
    call_command("seed_core", "--tenant-code=SEEDCORE")

    tenant = Tenant.objects.get(code="SEEDCORE")
    assert tenant.country_code == "MG"

    assert Group.objects.filter(name="resp_production").exists()
    assert Group.objects.count() >= 11

    assert User.objects.filter(email="demo.production@seedcore.widehalo.local").exists()
    assert User.objects.filter(email="demo.commercial@seedcore.widehalo.local").exists()
    assert User.objects.filter(email="demo.admin@seedcore.widehalo.local").exists()

    production_user = User.objects.get(email="demo.production@seedcore.widehalo.local")
    assert production_user.groups.filter(name="resp_production").exists()


def test_seed_core_is_idempotent() -> None:
    call_command("seed_core", "--tenant-code=SEEDCORE2")
    call_command("seed_core", "--tenant-code=SEEDCORE2")

    assert Tenant.objects.filter(code="SEEDCORE2").count() == 1
    assert User.objects.filter(email="demo.production@seedcore2.widehalo.local").count() == 1


def test_seed_core_preloads_helpdesk_ticket_type_catalog() -> None:
    from apps.core.tests.utils import use_tenant
    from apps.helpdesk.models import HlpTicketTypeCatalog

    call_command("seed_core", "--tenant-code=SEEDCORE3")

    tenant = Tenant.objects.get(code="SEEDCORE3")
    with use_tenant(tenant.id):
        assert HlpTicketTypeCatalog.objects.filter(tenant=tenant).count() > 30
