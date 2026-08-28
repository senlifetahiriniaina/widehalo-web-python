"""Test leger de `seed_sales` (T10, comble le trou du retest des 14 couches
— ce fichier n'existait pas encore lors de la premiere passe) : verifie que
la commande produit un devis accepte converti en commande confirmee — et
qu'une relance ne duplique rien."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant
from apps.sales.models import SalesOrder, SalesQuotation

pytestmark = pytest.mark.django_db


def test_seed_sales_creates_coherent_demo_dataset() -> None:
    call_command("seed_core", "--tenant-code=SEEDSAL")
    call_command("seed_sales", "--tenant-code=SEEDSAL")

    tenant = Tenant.objects.get(code="SEEDSAL")
    with activate_tenant(tenant.id):
        quotation = SalesQuotation.objects.get(tenant=tenant)
        assert quotation.state == SalesQuotation.STATE_ACCEPTED
        assert quotation.lines.count() >= 1

        order = SalesOrder.objects.get(tenant=tenant, quotation=quotation)
        assert order.state == SalesOrder.STATE_CONFIRMED


def test_seed_sales_is_idempotent() -> None:
    call_command("seed_core", "--tenant-code=SEEDSAL2")
    call_command("seed_sales", "--tenant-code=SEEDSAL2")
    call_command("seed_sales", "--tenant-code=SEEDSAL2")

    tenant = Tenant.objects.get(code="SEEDSAL2")
    with activate_tenant(tenant.id):
        assert SalesQuotation.objects.filter(tenant=tenant).count() == 1
        assert SalesOrder.objects.filter(tenant=tenant).count() == 1
