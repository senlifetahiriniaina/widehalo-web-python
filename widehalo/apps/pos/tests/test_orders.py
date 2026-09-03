"""Commandes de caisse — lignes produit/service, règlements, validation
(POS-1, POS-4, POS-5, POS-8, POS-9)."""

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
from apps.pos.models import PosOrder, PosOrderLine, PosPaymentMethod
from apps.pos.services.orders import add_line, add_payment, cancel_order, create_draft_order, validate_order
from apps.pos.tests.factories import PosPaymentMethodFactory, PosSessionFactory
from apps.stocks.models import StkLocation, StkPicking
from apps.stocks.tests.factories import StkLocationFactory, StkQuantFactory, StkWarehouseFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    t = Tenant.objects.create(code="POS-ORD", name="POS Orders Tenant")
    with use_tenant(t.id):
        yield t


def _sellable_variant(tenant: Tenant):
    template = ProductTemplateFactory(tenant=tenant, is_sellable=True, is_active=True)
    return ProductVariantFactory(tenant=tenant, template=template, is_active=True)


def test_add_line_of_type_service_never_references_a_variant_nor_stock(tenant) -> None:
    session = PosSessionFactory(tenant=tenant)
    order = create_draft_order(tenant, session=session, client_uuid=uuid.uuid4(), local_sequence=1)

    line = add_line(
        order,
        line_type=PosOrderLine.TYPE_SERVICE,
        description="Retouche",
        qty=Decimal(1),
        unit_price=Decimal(5000),
        service_basis=PosOrderLine.SERVICE_BASIS_FORFAIT,
    )

    assert line.variant_id is None
    assert line.stock_move_id is None


def test_add_line_of_type_product_revalidates_sellability_server_side(tenant) -> None:
    session = PosSessionFactory(tenant=tenant)
    order = create_draft_order(tenant, session=session, client_uuid=uuid.uuid4(), local_sequence=1)

    with pytest.raises(ValidationError):
        add_line(order, line_type=PosOrderLine.TYPE_PRODUCT, variant_id=uuid.uuid4(), qty=Decimal(1))


def test_add_line_applies_the_default_sale_tax_rate_as_a_snapshot(tenant) -> None:
    AccTaxFactory(tenant=tenant, type=AccTax.TYPE_SALE, rate=Decimal("20.000"))
    session = PosSessionFactory(tenant=tenant)
    order = create_draft_order(tenant, session=session, client_uuid=uuid.uuid4(), local_sequence=1)

    line = add_line(
        order, line_type=PosOrderLine.TYPE_SERVICE, description="Service", qty=Decimal(1), unit_price=Decimal(1000)
    )

    assert line.tax_rate == Decimal("20.000")
    assert line.subtotal == Decimal("1000.0000")
    assert line.tax_amount == Decimal("200.0000")
    assert line.total == Decimal("1200.0000")


def test_add_payment_requires_a_reference_when_the_method_demands_one(tenant) -> None:
    session = PosSessionFactory(tenant=tenant)
    order = create_draft_order(tenant, session=session, client_uuid=uuid.uuid4(), local_sequence=1)
    add_line(order, line_type=PosOrderLine.TYPE_SERVICE, description="Service", qty=Decimal(1), unit_price=Decimal(1000))
    order.refresh_from_db()
    mobile_money = PosPaymentMethodFactory(
        tenant=tenant, type=PosPaymentMethod.TYPE_MOBILE_MONEY, requires_reference=True
    )

    with pytest.raises(ValidationError):
        add_payment(order, method=mobile_money, amount=order.amount_total, reference="")

    add_payment(order, method=mobile_money, amount=order.amount_total, reference="MVOLA-123456")


def test_validate_order_requires_full_payment_and_assigns_a_register_prefixed_number(tenant) -> None:
    session = PosSessionFactory(tenant=tenant)
    order = create_draft_order(tenant, session=session, client_uuid=uuid.uuid4(), local_sequence=1)
    add_line(order, line_type=PosOrderLine.TYPE_SERVICE, description="Service", qty=Decimal(1), unit_price=Decimal(1000))
    order.refresh_from_db()
    cash = PosPaymentMethodFactory(tenant=tenant, type="cash")

    with pytest.raises(ValidationError):
        validate_order(order, date=dt.date(2026, 1, 15))  # aucun règlement encore

    add_payment(order, method=cash, amount=order.amount_total)
    validated = validate_order(order, date=dt.date(2026, 1, 15))

    assert validated.state == PosOrder.STATE_VALIDATED
    assert validated.number.startswith(session.register.code)


def test_validate_order_moves_real_stock_for_product_lines_only(tenant) -> None:
    warehouse = StkWarehouseFactory(tenant=tenant)
    internal_location = StkLocationFactory(tenant=tenant, warehouse=warehouse)
    StkLocationFactory(tenant=tenant, warehouse=warehouse, type=StkLocation.TYPE_CLIENT)
    variant = _sellable_variant(tenant)
    StkQuantFactory(tenant=tenant, variant_id=variant.id, location=internal_location, qty=Decimal(10))

    session = PosSessionFactory(tenant=tenant)
    session.register.warehouse_id = warehouse.id
    session.register.save(update_fields=["warehouse_id"])

    order = create_draft_order(tenant, session=session, client_uuid=uuid.uuid4(), local_sequence=1)
    product_line = add_line(order, line_type=PosOrderLine.TYPE_PRODUCT, variant_id=variant.id, qty=Decimal(2))
    service_line = add_line(
        order, line_type=PosOrderLine.TYPE_SERVICE, description="Service", qty=Decimal(1), unit_price=Decimal(500)
    )
    order.refresh_from_db()
    cash = PosPaymentMethodFactory(tenant=tenant, type="cash")
    add_payment(order, method=cash, amount=order.amount_total)
    validate_order(order, date=dt.date(2026, 1, 15))

    product_line.refresh_from_db()
    service_line.refresh_from_db()
    assert product_line.stock_move_id is not None
    assert service_line.stock_move_id is None

    picking = StkPicking.objects.get(id=product_line.stock_move_id)
    assert picking.state == StkPicking.STATE_DONE
    assert picking.type == StkPicking.TYPE_SORTIE


def test_a_validated_order_can_never_be_modified_or_cancelled(tenant) -> None:
    session = PosSessionFactory(tenant=tenant)
    order = create_draft_order(tenant, session=session, client_uuid=uuid.uuid4(), local_sequence=1)
    add_line(order, line_type=PosOrderLine.TYPE_SERVICE, description="Service", qty=Decimal(1), unit_price=Decimal(1000))
    order.refresh_from_db()
    cash = PosPaymentMethodFactory(tenant=tenant, type="cash")
    add_payment(order, method=cash, amount=order.amount_total)
    validate_order(order, date=dt.date(2026, 1, 15))

    with pytest.raises(ValidationError):
        add_line(order, line_type=PosOrderLine.TYPE_SERVICE, description="Autre", qty=Decimal(1), unit_price=Decimal(1))
    with pytest.raises(ValidationError):
        cancel_order(order)
