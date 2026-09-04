"""Retour / avoir (cahier §13.5, « Retour, échange, avoir »)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounting.models import AccTax
from apps.accounting.tests.factories import AccTaxFactory
from apps.catalog.tests.factories import ProductTemplateFactory, ProductVariantFactory
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.pos.models import PosOrder, PosOrderLine
from apps.pos.services.orders import (
    add_line,
    add_payment,
    create_draft_order,
    create_return_order,
    validate_order,
)
from apps.pos.tests.factories import PosPaymentMethodFactory, PosSessionFactory
from apps.stocks.models import StkLocation, StkPicking
from apps.stocks.tests.factories import StkLocationFactory, StkQuantFactory, StkWarehouseFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    t = Tenant.objects.create(code="POS-RET", name="POS Returns Tenant")
    with use_tenant(t.id):
        yield t


def _validated_sale(tenant, session, *, variant_id=None, qty=Decimal(2), unit_price=Decimal(1000)):
    order = create_draft_order(tenant, session=session, client_uuid=uuid.uuid4(), local_sequence=1)
    line_type = PosOrderLine.TYPE_PRODUCT if variant_id else PosOrderLine.TYPE_SERVICE
    line = add_line(
        order,
        line_type=line_type,
        variant_id=variant_id,
        description="Article vendu",
        qty=qty,
        unit_price=unit_price,
    )
    order.refresh_from_db()
    cash = PosPaymentMethodFactory(tenant=tenant, type="cash")
    add_payment(order, method=cash, amount=order.amount_total)
    validate_order(order, date=dt.date(2026, 1, 15))
    order.refresh_from_db()
    return order, line, cash


def test_return_refunds_proportionally_to_the_original_line_price(tenant) -> None:
    AccTaxFactory(tenant=tenant, type=AccTax.TYPE_SALE, rate=Decimal("20.000"))
    session = PosSessionFactory(tenant=tenant)
    origin_order, origin_line, cash = _validated_sale(
        tenant, session, qty=Decimal(2), unit_price=Decimal(1000)
    )
    # 2 x 1000 HT = 2000 HT, TVA 20% = 400, total = 2400 pour 2 unités.

    return_order = create_return_order(
        tenant,
        origin_order=origin_order,
        session=session,
        client_uuid=uuid.uuid4(),
        local_sequence=2,
        return_lines=[{"origin_line_id": origin_line.id, "qty": Decimal(1)}],
        refund_method=cash,
        date=dt.date(2026, 1, 16),
    )

    assert return_order.order_type == PosOrder.TYPE_RETURN
    assert return_order.origin_order_id == origin_order.id
    assert return_order.state == PosOrder.STATE_VALIDATED
    # Moitié de la ligne d'origine (1 unité sur 2) : 1000 HT + 200 TVA = 1200.
    assert return_order.amount_total == Decimal("1200.0000")


def test_return_cannot_exceed_the_originally_sold_quantity(tenant) -> None:
    session = PosSessionFactory(tenant=tenant)
    origin_order, origin_line, cash = _validated_sale(tenant, session, qty=Decimal(1))

    with pytest.raises(ValidationError):
        create_return_order(
            tenant,
            origin_order=origin_order,
            session=session,
            client_uuid=uuid.uuid4(),
            local_sequence=2,
            return_lines=[{"origin_line_id": origin_line.id, "qty": Decimal(2)}],
            refund_method=cash,
            date=dt.date(2026, 1, 16),
        )


def test_return_of_a_product_line_puts_the_stock_back(tenant) -> None:
    warehouse = StkWarehouseFactory(tenant=tenant)
    internal_location = StkLocationFactory(tenant=tenant, warehouse=warehouse)
    StkLocationFactory(tenant=tenant, warehouse=warehouse, type=StkLocation.TYPE_CLIENT)
    template = ProductTemplateFactory(tenant=tenant)
    variant = ProductVariantFactory(tenant=tenant, template=template)
    StkQuantFactory(
        tenant=tenant, variant_id=variant.id, location=internal_location, qty=Decimal(10)
    )

    session = PosSessionFactory(tenant=tenant)
    session.register.warehouse_id = warehouse.id
    session.register.save(update_fields=["warehouse_id"])

    origin_order, origin_line, cash = _validated_sale(
        tenant, session, variant_id=variant.id, qty=Decimal(3), unit_price=Decimal(1000)
    )

    return_order = create_return_order(
        tenant,
        origin_order=origin_order,
        session=session,
        client_uuid=uuid.uuid4(),
        local_sequence=2,
        return_lines=[{"origin_line_id": origin_line.id, "qty": Decimal(1)}],
        refund_method=cash,
        date=dt.date(2026, 1, 16),
    )

    return_line = return_order.lines.first()
    assert return_line.stock_move_id is not None
    picking = StkPicking.objects.get(id=return_line.stock_move_id)
    assert picking.type == StkPicking.TYPE_ENTREE
    assert picking.state == StkPicking.STATE_DONE
