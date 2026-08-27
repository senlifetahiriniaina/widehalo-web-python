"""Schemas django-ninja de l'API `sales` (§5.5.7, S1 : devis, S2 :
commande de vente). Montants toujours `Decimal` (jamais `float`,
convention projet)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from ninja import Schema


class QuotationLineIn(Schema):
    variant_id: str | None = None
    description: str = ""
    qty: Decimal = Decimal(1)
    uom: str = ""
    unit_price: Decimal | None = None
    discount_pct: Decimal = Decimal(0)
    is_custom: bool = False
    source: str = "stock"


class QuotationIn(Schema):
    partner_id: str
    date: dt.date
    contact: str = ""
    source_lead_id: str | None = None
    validity_date: dt.date | None = None
    pricelist_id: str | None = None
    currency: str = "MGA"
    payment_term_id: str | None = None
    incoterm: str = ""
    delivery_address: str = ""
    notes: str = ""
    internal_notes: str = ""
    lines: list[QuotationLineIn] = []


class QuotationDeclineIn(Schema):
    reason: str = ""


class QuotationLineOut(Schema):
    id: str
    sequence: int
    variant_id: str | None
    is_custom: bool
    description: str
    qty: Decimal
    uom: str
    unit_price: Decimal
    discount_pct: Decimal
    subtotal: Decimal
    source: str


class QuotationOut(Schema):
    id: str
    reference: str
    partner_id: str
    contact: str
    source_lead_id: str | None
    source_lead_reference: str
    date: dt.date
    validity_date: dt.date | None
    currency: str
    incoterm: str
    state: str
    amount_untaxed: Decimal
    amount_tax: Decimal
    amount_total: Decimal
    amount_total_mga: Decimal
    notes: str
    lines: list[QuotationLineOut]


class OrderLineIn(Schema):
    variant_id: str | None = None
    description: str = ""
    qty: Decimal = Decimal(1)
    uom: str = ""
    unit_price: Decimal | None = None
    discount_pct: Decimal = Decimal(0)
    is_custom: bool = False
    source: str = "stock"
    billing_policy: str = "on_ordered_qty"
    deposit_pct: Decimal | None = None


class OrderIn(Schema):
    partner_id: str
    date: dt.date
    quotation_id: str | None = None
    contact: str = ""
    source_lead_id: str | None = None
    commitment_date: dt.date | None = None
    pricelist_id: str | None = None
    currency: str = "MGA"
    payment_term_id: str | None = None
    incoterm: str = ""
    delivery_address: str = ""
    notes: str = ""
    internal_notes: str = ""
    lines: list[OrderLineIn] = []


class OrderCancelIn(Schema):
    reason: str = ""


class OrderDeliverIn(Schema):
    partial: bool = False


class OrderInvoiceIn(Schema):
    # Ids de `SalesOrderLine` a facturer (facturation partielle) ; liste
    # vide/omise = toutes les lignes de la commande.
    line_ids: list[str] = []


class OrderInvoiceOut(Schema):
    invoice_id: str | None
    detail: str = ""


class OrderLineOut(Schema):
    id: str
    sequence: int
    variant_id: str | None
    is_custom: bool
    description: str
    qty: Decimal
    uom: str
    unit_price: Decimal
    discount_pct: Decimal
    subtotal: Decimal
    source: str
    qty_delivered: Decimal
    qty_invoiced: Decimal
    billing_policy: str
    deposit_pct: Decimal | None


class RecurrenceIn(Schema):
    name: str
    interval: str
    start_date: dt.date
    template_order_id: str
    day_rule: str = ""
    end_date: dt.date | None = None


class RecurrenceOut(Schema):
    id: str
    name: str
    interval: str
    day_rule: str
    start_date: dt.date
    end_date: dt.date | None
    next_run: dt.date
    template_order_id: str
    is_active: bool


class OrderOut(Schema):
    id: str
    reference: str
    quotation_id: str | None
    partner_id: str
    contact: str
    source_lead_id: str | None
    source_lead_reference: str
    date: dt.date
    date_confirmed: dt.date | None
    commitment_date: dt.date | None
    currency: str
    incoterm: str
    state: str
    blocked_reason: str
    cancel_reason: str
    amount_untaxed: Decimal
    amount_tax: Decimal
    amount_total: Decimal
    amount_total_mga: Decimal
    notes: str
    is_recurring: bool
    invoiced_amount_mga: Decimal
    lines: list[OrderLineOut]
