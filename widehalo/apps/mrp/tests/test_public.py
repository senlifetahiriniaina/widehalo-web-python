"""Tests du contrat public de `mrp` (`apps/mrp/services/public.py`) —
seule surface que `sales` (et les autres apps metier) ont le droit
d'importer. Couvre ici le gap ajoute pour RG-SAL-3 (S3 du
sous-sequencement `sales`, cf. plan) : `create_manufacturing_order`."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.mrp.models import MrpOrder
from apps.mrp.services.bom import activate_bom, create_bom
from apps.mrp.services.public import create_manufacturing_order
from apps.mrp.tests.factories import MrpWorkshopFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def public_setup():
    tenant = Tenant.objects.create(code="MRP-PUB", name="MRP Public Tenant")
    with use_tenant(tenant.id):
        return tenant


def test_create_manufacturing_order_creates_real_order_when_bom_and_workshop_exist(
    public_setup,
) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        product_template_id = uuid.uuid4()
        variant_id = uuid.uuid4()
        bom = create_bom(tenant=tenant, code="BOM-PUB-1", product_template_id=product_template_id)
        activate_bom(bom)
        MrpWorkshopFactory(tenant=tenant)

        order_id = create_manufacturing_order(
            tenant=tenant,
            product_template_id=product_template_id,
            variant_id=variant_id,
            qty=Decimal("10"),
        )

        assert order_id is not None
        order = MrpOrder.objects.get(id=order_id)
        assert order.bom_id == bom.id
        assert order.variant_id == variant_id
        assert order.qty == Decimal("10")
        assert order.state == MrpOrder.STATE_DRAFT


def test_create_manufacturing_order_returns_none_without_active_bom(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        MrpWorkshopFactory(tenant=tenant)
        order_id = create_manufacturing_order(
            tenant=tenant,
            product_template_id=uuid.uuid4(),
            qty=Decimal("5"),
        )
        assert order_id is None
        assert not MrpOrder.objects.exists()


def test_create_manufacturing_order_returns_none_without_workshop(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        product_template_id = uuid.uuid4()
        bom = create_bom(tenant=tenant, code="BOM-PUB-2", product_template_id=product_template_id)
        activate_bom(bom)

        order_id = create_manufacturing_order(
            tenant=tenant,
            product_template_id=product_template_id,
            qty=Decimal("5"),
        )

        assert order_id is None
        assert not MrpOrder.objects.exists()
