"""Schemas django-ninja de l'API `pos` (§13.5). Montants toujours
`Decimal` (jamais `float`, convention projet)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from ninja import Schema

from apps.pos.models import PosOrder, PosOrderLine, PosPaymentMethod


class RegisterIn(Schema):
    code: str
    name: str
    warehouse_id: str | None = None


class RegisterOut(Schema):
    id: str
    code: str
    name: str
    warehouse_id: str | None
    is_active: bool


class PaymentMethodIn(Schema):
    code: str
    name: str
    type: str = PosPaymentMethod.TYPE_CASH
    requires_reference: bool = False
    default_account_type: str = PosPaymentMethod.ACCOUNT_TYPE_CASH
    account_id: str | None = None


class PaymentMethodOut(Schema):
    id: str
    code: str
    name: str
    type: str
    requires_reference: bool
    default_account_type: str
    account_id: str | None
    is_active: bool


class SessionOpenIn(Schema):
    register_id: str
    opening_cash_amount: Decimal = Decimal(0)


class SessionOut(Schema):
    id: str
    register_id: str
    register_code: str
    cashier_id: str
    state: str
    opened_at: dt.datetime
    closed_at: dt.datetime | None
    opening_cash_amount: Decimal
    closing_cash_counted: Decimal | None
    closing_cash_expected: Decimal | None
    cash_variance: Decimal | None
    cash_variance_reason: str
    closing_move_id: str | None
    local_sequence_last: int


class CashMovementIn(Schema):
    direction: str
    amount: Decimal
    reason: str


class SessionClosingPreviewOut(Schema):
    expected_cash: Decimal
    opening_cash_amount: Decimal


class SessionCloseIn(Schema):
    counted_cash: Decimal
    variance_reason: str = ""


class OrderLineIn(Schema):
    line_type: str = PosOrderLine.TYPE_PRODUCT
    variant_id: str | None = None
    description: str = ""
    qty: Decimal = Decimal(1)
    uom: str = ""
    unit_price: Decimal | None = None
    discount_pct: Decimal = Decimal(0)
    service_basis: str = ""
    is_deposit: bool = False


class OrderPaymentIn(Schema):
    method_id: str
    amount: Decimal
    reference: str = ""


class OrderSyncIn(Schema):
    client_uuid: str
    local_sequence: int
    order_type: str = PosOrder.TYPE_SALE
    document_type: str = PosOrder.DOCUMENT_TICKET
    partner_id: str | None = None
    source: str = PosOrder.SOURCE_ONLINE
    lines: list[OrderLineIn] = []
    payments: list[OrderPaymentIn] = []


class OrderSyncBatchIn(Schema):
    session_id: str
    orders: list[OrderSyncIn] = []


class OrderLineOut(Schema):
    id: str
    sequence: int
    line_type: str
    variant_id: str | None
    description: str
    qty: Decimal
    uom: str
    unit_price: Decimal
    discount_pct: Decimal
    tax_rate: Decimal
    subtotal: Decimal
    tax_amount: Decimal
    total: Decimal
    service_basis: str
    is_deposit: bool
    stock_move_id: str | None


class OrderPaymentOut(Schema):
    id: str
    method_id: str
    method_name: str
    amount: Decimal
    reference: str
    received_at: dt.datetime


class OrderOut(Schema):
    id: str
    session_id: str
    register_code: str
    client_uuid: str
    number: str
    local_sequence: int
    order_type: str
    origin_order_id: str | None
    document_type: str
    partner_id: str | None
    partner_name: str
    state: str
    source: str
    amount_untaxed: Decimal
    amount_tax: Decimal
    amount_total: Decimal
    reprint_count: int
    created_at: dt.datetime
    lines: list[OrderLineOut] = []
    payments: list[OrderPaymentOut] = []


class OrderSyncResultOut(Schema):
    """`order` absent (`None`) uniquement pour `outcome="rejected"` — la
    commande n'a alors jamais été créée (cf. `services.orders.sync_order`,
    rollback complet à la première `ValidationError`), `detail` porte
    alors le motif du rejet."""

    client_uuid: str
    outcome: str
    order: OrderOut | None = None
    detail: str = ""


class ReturnLineIn(Schema):
    origin_line_id: str
    qty: Decimal


class ReturnOrderIn(Schema):
    origin_order_id: str
    session_id: str
    client_uuid: str
    local_sequence: int
    return_lines: list[ReturnLineIn]
    refund_method_id: str
    refund_reference: str = ""


class CatalogSearchOut(Schema):
    id: str
    reference: str
    label: str
    unit_price_mga: Decimal


class PartnerSearchOut(Schema):
    id: str
    name: str
    nif: str


class SyncLogOut(Schema):
    id: str
    register_code: str
    client_uuid: str
    local_sequence: int | None
    outcome: str
    detail: str
    synced_at: dt.datetime
