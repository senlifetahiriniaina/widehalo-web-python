"""Test leger de `seed_purchase` (T10, comble le trou du retest des 14
couches — ce fichier n'existait pas encore lors de la premiere passe) :
verifie que la commande produit une demande d'achat approuvee et une
commande d'achat confirmee — et qu'une relance ne duplique rien."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant
from apps.purchase.models import PurOrder, PurRequisition

pytestmark = pytest.mark.django_db


def test_seed_purchase_creates_coherent_demo_dataset() -> None:
    call_command("seed_purchase", "--tenant-code=SEEDPUR")

    tenant = Tenant.objects.get(code="SEEDPUR")
    with activate_tenant(tenant.id):
        requisition = PurRequisition.objects.get(tenant=tenant)
        assert requisition.state == PurRequisition.STATE_APPROVED
        assert requisition.lines.count() >= 1

        order = PurOrder.objects.get(tenant=tenant, requisition=requisition)
        assert order.state == PurOrder.STATE_CONFIRMED
        assert order.lines.exists()


def test_seed_purchase_is_idempotent() -> None:
    call_command("seed_purchase", "--tenant-code=SEEDPUR2")
    call_command("seed_purchase", "--tenant-code=SEEDPUR2")

    tenant = Tenant.objects.get(code="SEEDPUR2")
    with activate_tenant(tenant.id):
        assert PurRequisition.objects.filter(tenant=tenant).count() == 1
        assert PurOrder.objects.filter(tenant=tenant).count() == 1
