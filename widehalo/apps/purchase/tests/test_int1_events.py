"""INT1 (chantier interactivite native inter-modules) : evenements
`purchase.order_confirmed`/`purchase.dispute_opened`/
`purchase.reorder_triggered` — completude des gaps de notification
identifies par lecture directe du code (cf. rapport de tache INT1)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.catalog.models import ProductTemplate, ProductVariant, UnitOfMeasure
from apps.core.models.event import EventLog
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.purchase.models import PurRequisition
from apps.purchase.services.orders import (
    add_order_line,
    confirm_order,
    create_order,
    open_order_dispute,
    send_order,
    submit_order_for_validation,
    validate_order,
)
from apps.purchase.services.reordering import create_reordering_rule, run_reordering

pytestmark = pytest.mark.django_db


@pytest.fixture
def orders_setup():
    tenant = Tenant.objects.create(code="PUR-INT1-ORD", name="Purchase INT1 Orders Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="pur-int1-ord@example.com", password="Str0ngPassw0rd!23"
        )
        return tenant, user


def _order_to_confirmed(tenant, user):
    order = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
    add_order_line(
        order,
        variant_id=uuid.uuid4(),
        description="Fil",
        qty=Decimal(1),
        unit_price_mga=Decimal(100),
    )
    submit_order_for_validation(order, user)
    validate_order(order, user)
    send_order(order, user)
    confirm_order(order, user)
    return order


def test_confirm_order_publishes_order_confirmed(orders_setup) -> None:
    tenant, user = orders_setup
    with use_tenant(tenant.id):
        order = _order_to_confirmed(tenant, user)

    event = EventLog.objects.get(event_type="purchase.order_confirmed", tenant_id=str(tenant.id))
    assert event.payload["order_id"] == str(order.id)
    assert event.payload["reference"] == order.reference


def test_open_order_dispute_publishes_dispute_opened(orders_setup) -> None:
    tenant, user = orders_setup
    with use_tenant(tenant.id):
        order = _order_to_confirmed(tenant, user)
        open_order_dispute(order, user, reason="Ecart facture > 2%")

    event = EventLog.objects.get(event_type="purchase.dispute_opened", tenant_id=str(tenant.id))
    assert event.payload["order_id"] == str(order.id)
    assert event.payload["reason"] == "Ecart facture > 2%"


def _make_variant(tenant, *, suffix="0001"):
    """`add_requisition_line` (appelee par `run_reordering`) resout
    `estimated_price_mga` via `catalog.services.public.get_variant_price`,
    qui exige un `ProductVariant` REEL — meme helper que
    `apps.purchase.tests.test_reordering`."""
    uom = UnitOfMeasure.objects.create(
        tenant=tenant, code=f"PC{suffix}", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
    )
    template = ProductTemplate.objects.create(
        tenant=tenant,
        name=f"Composant {suffix}",
        base_uom=uom,
        reference=f"TPL-PUR-INT1-{suffix}",
        base_price_mga=Decimal("1000"),
    )
    return ProductVariant.objects.create(
        tenant=tenant, template=template, reference=f"VAR-PUR-INT1-{suffix}"
    )


def test_run_reordering_publishes_reorder_triggered() -> None:
    tenant = Tenant.objects.create(code="PUR-INT1-REORD", name="Purchase INT1 Reordering Tenant")
    with use_tenant(tenant.id):
        User.objects.create_superuser(
            email="pur-int1-reord-admin@example.com", password="Str0ngPassw0rd!23"
        )
        variant = _make_variant(tenant, suffix="TRIG")
        create_reordering_rule(
            tenant=tenant, variant_id=variant.id, min_qty=Decimal(10), max_qty=Decimal(30)
        )
        requisitions = run_reordering(tenant)
        assert len(requisitions) == 1
        assert PurRequisition.objects.filter(tenant=tenant).count() == 1

    event = EventLog.objects.get(event_type="purchase.reorder_triggered", tenant_id=str(tenant.id))
    assert event.payload["count"] == 1
    assert event.payload["requisition_ids"] == [str(requisitions[0].id)]


def test_run_reordering_does_not_publish_when_nothing_is_triggered() -> None:
    tenant = Tenant.objects.create(
        code="PUR-INT1-REORD-NOOP", name="Purchase INT1 Reordering Noop Tenant"
    )
    with use_tenant(tenant.id):
        User.objects.create_superuser(
            email="pur-int1-reord-noop-admin@example.com", password="Str0ngPassw0rd!23"
        )
        create_reordering_rule(
            tenant=tenant, variant_id=uuid.uuid4(), min_qty=Decimal(0), max_qty=Decimal(30)
        )
        assert run_reordering(tenant) == []

    assert not EventLog.objects.filter(
        event_type="purchase.reorder_triggered", tenant_id=str(tenant.id)
    ).exists()
