"""Test leger de `seed_stocks` (T10, comble le trou du retest des 14
couches — ce fichier n'existait pas encore lors de la premiere passe) :
verifie que la commande produit un mouvement de reception valide (RG-STK-1
double-entree materialisee) — et qu'une relance ne duplique rien."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant
from apps.stocks.models import StkMove, StkQuant, StkWarehouse

pytestmark = pytest.mark.django_db


def test_seed_stocks_creates_coherent_demo_dataset() -> None:
    call_command("seed_stocks", "--tenant-code=SEEDSTK")

    tenant = Tenant.objects.get(code="SEEDSTK")
    with activate_tenant(tenant.id):
        warehouse = StkWarehouse.objects.get(tenant=tenant, code="WH-DEMO")
        assert warehouse.locations.count() == 2

        move = StkMove.objects.get(tenant=tenant)
        assert move.state == StkMove.STATE_DONE
        assert StkQuant.objects.filter(tenant=tenant).count() == 2


def test_seed_stocks_is_idempotent() -> None:
    call_command("seed_stocks", "--tenant-code=SEEDSTK2")
    call_command("seed_stocks", "--tenant-code=SEEDSTK2")

    tenant = Tenant.objects.get(code="SEEDSTK2")
    with activate_tenant(tenant.id):
        assert StkWarehouse.objects.filter(tenant=tenant).count() == 1
        assert StkMove.objects.filter(tenant=tenant).count() == 1
