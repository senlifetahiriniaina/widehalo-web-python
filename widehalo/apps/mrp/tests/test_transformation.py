"""A2 (L4 Agro, cf. docs/planning/2026-refonte-ux-sprints.md §5) : ordre
de transformation + rendement + généalogie de lot
(`apps.mrp.services.transformation`). Même idiome que `test_orders.py`
pour driver le cycle de vie `MrpOrder`."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from apps.core.tests.factories import TenantFactory, UserFactory
from apps.core.tests.utils import use_tenant
from apps.mrp.services.orders import (
    confirm_order,
    reserve_order,
    send_to_quality_control,
    start_order,
)
from apps.mrp.services.transformation import (
    finish_transformation_order,
    order_genealogy,
    order_yield,
    record_component_consumption,
)
from apps.mrp.tests.factories import MrpOrderComponentFactory, MrpOrderFactory
from apps.stocks.tests.factories import StkLocationFactory

pytestmark = pytest.mark.django_db


def _order_at_quality_control(tenant, user, **kwargs):
    order = MrpOrderFactory(tenant=tenant, qty=Decimal("100"), **kwargs)
    confirm_order(order, user)
    reserve_order(order, user)
    start_order(order, user)
    send_to_quality_control(order, user)
    return order


def test_order_yield_computes_real_vs_theoretical() -> None:
    tenant = TenantFactory()
    user = UserFactory()
    with use_tenant(tenant.id):
        order = _order_at_quality_control(tenant, user)
        finish_transformation_order(
            order, user, qty_produced=Decimal("95"), output_lot_name="", location_to_id=None
        )

        data = order_yield(order)
        assert data["qty_target"] == Decimal("100")
        assert data["qty_produced"] == Decimal("95")
        assert data["yield_pct"] == Decimal("95")


def test_finish_without_output_lot_name_behaves_like_plain_finish() -> None:
    """Aucune régression pour un ordre textile/hors-agro qui n'a pas besoin
    de traçabilité de lot : pas de `location_to_id` requis."""
    tenant = TenantFactory()
    user = UserFactory()
    with use_tenant(tenant.id):
        order = _order_at_quality_control(tenant, user)
        order = finish_transformation_order(
            order, user, qty_produced=Decimal("100"), output_lot_name="", location_to_id=None
        )
        assert order.state == "done"
        assert order.output_lot_name == ""


def test_finish_with_output_lot_name_requires_a_location() -> None:
    from django.core.exceptions import ValidationError

    tenant = TenantFactory()
    user = UserFactory()
    with use_tenant(tenant.id):
        order = _order_at_quality_control(tenant, user)
        with pytest.raises(ValidationError):
            finish_transformation_order(
                order, user, qty_produced=Decimal("100"), output_lot_name="PF-2026-001",
                location_to_id=None,
            )


def test_finish_with_output_lot_name_creates_stock_and_genealogy() -> None:
    tenant = TenantFactory()
    user = UserFactory()
    with use_tenant(tenant.id):
        location = StkLocationFactory(tenant=tenant)
        order = _order_at_quality_control(tenant, user)
        component = MrpOrderComponentFactory(
            tenant=tenant, order=order, qty_planned=Decimal("50"), variant_id=uuid.uuid4()
        )
        record_component_consumption(component, lot_name="MP-2026-001", qty_consumed=Decimal("48"))

        order = finish_transformation_order(
            order,
            user,
            qty_produced=Decimal("95"),
            output_lot_name="PF-2026-001",
            location_to_id=location.id,
        )

        assert order.output_lot_name == "PF-2026-001"
        genealogy = order_genealogy(order)
        assert genealogy is not None
        assert genealogy["ancestors"][0]["lot_name"] == "MP-2026-001"
        assert genealogy["ancestors"][0]["qty"] == Decimal("48")


def test_finish_transformation_order_rolls_back_on_stock_reception_failure() -> None:
    """Régression : avant le correctif, `finish_order` (transition FSM)
    s'exécutait hors transaction — un `location_to_id` invalide faisait
    échouer `receive_production_output` APRÈS que l'ordre soit déjà
    `done` en base, laissant un ordre clos sans aucune réception de stock
    ni généalogie. Toute l'opération doit désormais réussir ou échouer
    ensemble."""
    import uuid as uuid_module

    from apps.stocks.models import StkLocation

    tenant = TenantFactory()
    user = UserFactory()
    with use_tenant(tenant.id):
        order = _order_at_quality_control(tenant, user)
        bogus_location_id = uuid_module.uuid4()
        assert not StkLocation.objects.filter(id=bogus_location_id).exists()

        with pytest.raises(StkLocation.DoesNotExist):
            finish_transformation_order(
                order,
                user,
                qty_produced=Decimal("95"),
                output_lot_name="PF-ROLLBACK-1",
                location_to_id=bogus_location_id,
            )

        order.refresh_from_db()
        assert order.state == "quality_control"
        assert order.output_lot_name == ""


def test_record_component_consumption_rejects_negative_qty() -> None:
    from django.core.exceptions import ValidationError

    tenant = TenantFactory()
    with use_tenant(tenant.id):
        component = MrpOrderComponentFactory(tenant=tenant)
        with pytest.raises(ValidationError):
            record_component_consumption(component, lot_name="X", qty_consumed=Decimal("-1"))


def test_order_genealogy_is_none_without_output_lot() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        order = MrpOrderFactory(tenant=tenant)
        assert order_genealogy(order) is None
