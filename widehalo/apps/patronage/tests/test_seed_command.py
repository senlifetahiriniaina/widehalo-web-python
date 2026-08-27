"""Test leger de `seed_patronage` (T10) : verifie que la commande produit
un patron valide avec piece/geometrie/consommation/marker, et qu'une
relance ne duplique rien."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant
from apps.patronage.models import PatMarker, PatPattern

pytestmark = pytest.mark.django_db


def test_seed_patronage_creates_coherent_demo_dataset() -> None:
    call_command("seed_patronage", "--tenant-code=SEEDPAT")

    tenant = Tenant.objects.get(code="SEEDPAT")
    with activate_tenant(tenant.id):
        pattern = PatPattern.objects.get(tenant=tenant, code="PAT-CHEMISE-DEMO")
        assert pattern.state == PatPattern.STATE_VALIDATED
        assert pattern.pieces.count() >= 1
        assert pattern.pieces.first().geometries.count() == len(pattern.size_chart.sizes)
        assert pattern.consumptions.exists()
        assert pattern.markers.exists()


def test_seed_patronage_is_idempotent() -> None:
    call_command("seed_patronage", "--tenant-code=SEEDPAT2")
    call_command("seed_patronage", "--tenant-code=SEEDPAT2")

    tenant = Tenant.objects.get(code="SEEDPAT2")
    with activate_tenant(tenant.id):
        assert PatPattern.objects.filter(tenant=tenant).count() == 1
        assert PatMarker.objects.filter(tenant=tenant).count() == 1
