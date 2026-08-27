"""API django-ninja du module `sales` (§5.5.7) — S1 : devis, S2 : commande
de vente. Depuis S3, `POST .../confirm` declenche aussi la qualification
d'origine par ligne (RG-SAL-3) comme effet de bord de `confirm_order` — pas
de nouvel endpoint dedie dans ce lot (le futur `GET .../procurement-plan`
du §5.5.7 est differe a S7, cf. plan). Facturation/recurrence/previsions
restent differees a S4-S7."""

from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from ninja import Router

from apps.core.services.permissions import require_permission
from apps.crm.services.public import get_lead_reference
from apps.sales.models import SalesOrder, SalesQuotation
from apps.sales.schemas import (
    OrderCancelIn,
    OrderDeliverIn,
    OrderIn,
    OrderLineOut,
    OrderOut,
    QuotationDeclineIn,
    QuotationIn,
    QuotationLineIn,
    QuotationLineOut,
    QuotationOut,
)
from apps.sales.services.orders import (
    add_order_line,
    cancel_order,
    confirm_order,
    create_order,
    mark_delivered,
)
from apps.sales.services.quotations import (
    accept_quotation,
    add_quotation_line,
    create_quotation,
    decline_quotation,
    send_quotation,
)

router = Router(tags=["sales"])


def _serialize_line(line) -> QuotationLineOut:  # type: ignore[no-untyped-def]
    return QuotationLineOut(
        id=str(line.id),
        sequence=line.sequence,
        variant_id=str(line.variant_id) if line.variant_id else None,
        is_custom=line.is_custom,
        description=line.description,
        qty=line.qty,
        uom=line.uom,
        unit_price=line.unit_price,
        discount_pct=line.discount_pct,
        subtotal=line.subtotal,
        source=line.source,
    )


def _serialize_quotation(quotation: SalesQuotation) -> QuotationOut:
    source_lead_reference = (
        get_lead_reference(quotation.source_lead_id) if quotation.source_lead_id else ""
    )
    return QuotationOut(
        id=str(quotation.id),
        reference=quotation.reference,
        partner_id=str(quotation.partner_id),
        contact=quotation.contact,
        source_lead_id=str(quotation.source_lead_id) if quotation.source_lead_id else None,
        source_lead_reference=source_lead_reference,
        date=quotation.date,
        validity_date=quotation.validity_date,
        currency=quotation.currency,
        incoterm=quotation.incoterm,
        state=quotation.state,
        amount_untaxed=quotation.amount_untaxed,
        amount_tax=quotation.amount_tax,
        amount_total=quotation.amount_total,
        amount_total_mga=quotation.amount_total_mga,
        notes=quotation.notes,
        lines=[_serialize_line(line) for line in quotation.lines.all()],
    )


# NOTE ordre des decorateurs : `@router.xxx` DOIT etre le decorateur EXTERNE
# et `@require_permission(...)` l'INTERNE (juste au-dessus de `def`) — cf.
# apps/crm/api.py et apps/core/services/permissions.py pour le detail du
# bug de resolution corrige a T6 : l'ordre inverse ne bloque jamais aucune
# requete HTTP reelle malgre un `_required_permission` visible sur la
# fonction.
@router.get("/sales/quotations")
@require_permission("sales.view_salesquotation")
def list_quotations(request):
    quotations = SalesQuotation.objects.all().order_by("-created_at")
    return {"results": [_serialize_quotation(quotation) for quotation in quotations]}


@router.post("/sales/quotations")
@require_permission("sales.add_salesquotation")
def create_quotation_endpoint(request, payload: QuotationIn):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    quotation = create_quotation(
        tenant=tenant,
        partner_id=uuid.UUID(payload.partner_id),
        date=payload.date,
        salesperson=request.auth,
        currency=payload.currency,
        source_lead_id=uuid.UUID(payload.source_lead_id) if payload.source_lead_id else None,
        contact=payload.contact,
        validity_date=payload.validity_date,
        pricelist_id=uuid.UUID(payload.pricelist_id) if payload.pricelist_id else None,
        payment_term_id=uuid.UUID(payload.payment_term_id) if payload.payment_term_id else None,
        incoterm=payload.incoterm,
        delivery_address=payload.delivery_address,
        notes=payload.notes,
        internal_notes=payload.internal_notes,
    )
    for index, line in enumerate(payload.lines):
        add_quotation_line(
            quotation,
            variant_id=uuid.UUID(line.variant_id) if line.variant_id else None,
            description=line.description,
            qty=line.qty,
            uom=line.uom,
            unit_price=line.unit_price,
            discount_pct=line.discount_pct,
            is_custom=line.is_custom,
            source=line.source,
            sequence=index,
        )
    quotation.refresh_from_db()
    return _serialize_quotation(quotation)


@router.get("/sales/quotations/{quotation_id}")
@require_permission("sales.view_salesquotation")
def get_quotation_endpoint(request, quotation_id: str):
    quotation = get_object_or_404(SalesQuotation, id=quotation_id)
    return _serialize_quotation(quotation)


@router.post("/sales/quotations/{quotation_id}/lines")
@require_permission("sales.change_salesquotation")
def add_quotation_line_endpoint(request, quotation_id: str, payload: QuotationLineIn):
    quotation = get_object_or_404(SalesQuotation, id=quotation_id)
    add_quotation_line(
        quotation,
        variant_id=uuid.UUID(payload.variant_id) if payload.variant_id else None,
        description=payload.description,
        qty=payload.qty,
        uom=payload.uom,
        unit_price=payload.unit_price,
        discount_pct=payload.discount_pct,
        is_custom=payload.is_custom,
        source=payload.source,
        sequence=quotation.lines.count(),
    )
    quotation.refresh_from_db()
    return _serialize_quotation(quotation)


@router.post("/sales/quotations/{quotation_id}/send")
@require_permission("sales.change_salesquotation")
def send_quotation_endpoint(request, quotation_id: str):
    quotation = get_object_or_404(SalesQuotation, id=quotation_id)
    try:
        send_quotation(quotation)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_quotation(quotation)


@router.post("/sales/quotations/{quotation_id}/accept")
@require_permission("sales.change_salesquotation")
def accept_quotation_endpoint(request, quotation_id: str):
    quotation = get_object_or_404(SalesQuotation, id=quotation_id)
    try:
        accept_quotation(quotation)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_quotation(quotation)


@router.post("/sales/quotations/{quotation_id}/decline")
@require_permission("sales.change_salesquotation")
def decline_quotation_endpoint(request, quotation_id: str, payload: QuotationDeclineIn):
    quotation = get_object_or_404(SalesQuotation, id=quotation_id)
    try:
        decline_quotation(quotation, reason=payload.reason)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_quotation(quotation)


def _serialize_order_line(line) -> OrderLineOut:  # type: ignore[no-untyped-def]
    return OrderLineOut(
        id=str(line.id),
        sequence=line.sequence,
        variant_id=str(line.variant_id) if line.variant_id else None,
        is_custom=line.is_custom,
        description=line.description,
        qty=line.qty,
        uom=line.uom,
        unit_price=line.unit_price,
        discount_pct=line.discount_pct,
        subtotal=line.subtotal,
        source=line.source,
        qty_delivered=line.qty_delivered,
        qty_invoiced=line.qty_invoiced,
    )


def _serialize_order(order: SalesOrder) -> OrderOut:
    source_lead_reference = get_lead_reference(order.source_lead_id) if order.source_lead_id else ""
    return OrderOut(
        id=str(order.id),
        reference=order.reference,
        quotation_id=str(order.quotation_id) if order.quotation_id else None,
        partner_id=str(order.partner_id),
        contact=order.contact,
        source_lead_id=str(order.source_lead_id) if order.source_lead_id else None,
        source_lead_reference=source_lead_reference,
        date=order.date,
        date_confirmed=order.date_confirmed,
        commitment_date=order.commitment_date,
        currency=order.currency,
        incoterm=order.incoterm,
        state=order.state,
        blocked_reason=order.blocked_reason,
        cancel_reason=order.cancel_reason,
        amount_untaxed=order.amount_untaxed,
        amount_tax=order.amount_tax,
        amount_total=order.amount_total,
        amount_total_mga=order.amount_total_mga,
        notes=order.notes,
        is_recurring=order.is_recurring,
        lines=[_serialize_order_line(line) for line in order.lines.all()],
    )


@router.get("/sales/orders")
@require_permission("sales.view_salesorder")
def list_orders(request):
    orders = SalesOrder.objects.all().order_by("-created_at")
    return {"results": [_serialize_order(order) for order in orders]}


@router.post("/sales/orders")
@require_permission("sales.add_salesorder")
def create_order_endpoint(request, payload: OrderIn):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    order = create_order(
        tenant=tenant,
        partner_id=uuid.UUID(payload.partner_id),
        date=payload.date,
        salesperson=request.auth,
        currency=payload.currency,
        source_lead_id=uuid.UUID(payload.source_lead_id) if payload.source_lead_id else None,
        contact=payload.contact,
        commitment_date=payload.commitment_date,
        pricelist_id=uuid.UUID(payload.pricelist_id) if payload.pricelist_id else None,
        payment_term_id=uuid.UUID(payload.payment_term_id) if payload.payment_term_id else None,
        incoterm=payload.incoterm,
        delivery_address=payload.delivery_address,
        notes=payload.notes,
        internal_notes=payload.internal_notes,
    )
    for index, line in enumerate(payload.lines):
        add_order_line(
            order,
            variant_id=uuid.UUID(line.variant_id) if line.variant_id else None,
            description=line.description,
            qty=line.qty,
            uom=line.uom,
            unit_price=line.unit_price,
            discount_pct=line.discount_pct,
            is_custom=line.is_custom,
            source=line.source,
            sequence=index,
        )
    order.refresh_from_db()
    return _serialize_order(order)


@router.get("/sales/orders/{order_id}")
@require_permission("sales.view_salesorder")
def get_order_endpoint(request, order_id: str):
    order = get_object_or_404(SalesOrder, id=order_id)
    return _serialize_order(order)


@router.post("/sales/orders/{order_id}/confirm")
@require_permission("sales.change_salesorder")
def confirm_order_endpoint(request, order_id: str):
    order = get_object_or_404(SalesOrder, id=order_id)
    try:
        confirm_order(order, request.auth)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_order(order)


@router.post("/sales/orders/{order_id}/deliver")
@require_permission("sales.change_salesorder")
def deliver_order_endpoint(request, order_id: str, payload: OrderDeliverIn):
    order = get_object_or_404(SalesOrder, id=order_id)
    try:
        mark_delivered(order, request.auth, partial=payload.partial)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_order(order)


@router.post("/sales/orders/{order_id}/cancel")
@require_permission("sales.change_salesorder")
def cancel_order_endpoint(request, order_id: str, payload: OrderCancelIn):
    order = get_object_or_404(SalesOrder, id=order_id)
    try:
        cancel_order(order, request.auth, reason=payload.reason)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_order(order)
