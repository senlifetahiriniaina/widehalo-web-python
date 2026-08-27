"""Test leger de `seed_mrp` (T10) : verifie que la commande produit une
nomenclature active, un ordre de fabrication avance en production, un CRA
valide, un CRI et un rebut — et qu'une relance ne duplique rien."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant
from apps.mrp.models import MrpBom, MrpCra, MrpCri, MrpOrder, MrpScrap

pytestmark = pytest.mark.django_db


def test_seed_mrp_creates_coherent_demo_dataset() -> None:
    call_command("seed_mrp", "--tenant-code=SEEDMRP")

    tenant = Tenant.objects.get(code="SEEDMRP")
    with activate_tenant(tenant.id):
        bom = MrpBom.objects.get(tenant=tenant, state=MrpBom.STATE_ACTIVE)
        assert bom.lines.count() >= 1

        order = MrpOrder.objects.get(tenant=tenant, bom=bom)
        assert order.state == MrpOrder.STATE_IN_PRODUCTION
        assert order.components.exists()

        cra = MrpCra.objects.get(tenant=tenant, order=order)
        assert cra.state == MrpCra.STATE_VALIDATED

        assert MrpCri.objects.filter(tenant=tenant, order=order).exists()
        assert MrpScrap.objects.filter(tenant=tenant, order=order).exists()


def test_seed_mrp_is_idempotent() -> None:
    call_command("seed_mrp", "--tenant-code=SEEDMRP2")
    call_command("seed_mrp", "--tenant-code=SEEDMRP2")

    tenant = Tenant.objects.get(code="SEEDMRP2")
    with activate_tenant(tenant.id):
        assert MrpOrder.objects.filter(tenant=tenant).count() == 1
        assert MrpCra.objects.filter(tenant=tenant).count() == 1
        assert MrpCri.objects.filter(tenant=tenant).count() == 1
        assert MrpScrap.objects.filter(tenant=tenant).count() == 1
