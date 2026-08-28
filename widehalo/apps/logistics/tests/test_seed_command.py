"""Test leger de `seed_logistics` (T10, comble le trou du retest des 14
couches — ce fichier n'existait pas encore lors de la premiere passe) :
verifie que la commande produit une expedition avancee jusqu'a `in_transit`
— et qu'une relance ne duplique rien."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant
from apps.logistics.models import LogServiceProvider, LogShipment

pytestmark = pytest.mark.django_db


def test_seed_logistics_creates_coherent_demo_dataset() -> None:
    call_command("seed_logistics", "--tenant-code=SEEDLOG")

    tenant = Tenant.objects.get(code="SEEDLOG")
    with activate_tenant(tenant.id):
        carrier = LogServiceProvider.objects.get(tenant=tenant, code="CAR-DEMO")
        shipment = LogShipment.objects.get(tenant=tenant, carrier=carrier)
        assert shipment.state == LogShipment.STATE_IN_TRANSIT


def test_seed_logistics_is_idempotent() -> None:
    call_command("seed_logistics", "--tenant-code=SEEDLOG2")
    call_command("seed_logistics", "--tenant-code=SEEDLOG2")

    tenant = Tenant.objects.get(code="SEEDLOG2")
    with activate_tenant(tenant.id):
        assert LogServiceProvider.objects.filter(tenant=tenant).count() == 1
        assert LogShipment.objects.filter(tenant=tenant).count() == 1
