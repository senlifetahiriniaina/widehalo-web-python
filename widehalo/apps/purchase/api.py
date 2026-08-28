"""API django-ninja du module `purchase` (§5.6.6) — PU1 : demande d'achat
(`PurRequisition`/`PurRequisitionLine`), creation/listing, ajout de
lignes, et workflow `draft -> submitted -> approved/rejected`. PU3+PU4
(cf. plan) ajoute l'appel d'offres (RG-PUR-4, `PurRfq`) et la commande
d'achat (`PurOrder`, FSM complete §5.6.4, PUR-ROUT1, PUR-BULK1)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from apps.core.services.permissions import require_permission
from apps.core.services.workflow import TransitionPermissionError
from apps.purchase.models import (
    PurOrder,
    PurOrderLine,
    PurReorderingRule,
    PurRequisition,
    PurRfq,
    PurRfqResponse,
)
from apps.purchase.services.orders import (
    PurchaseApprovalRequiredError,
    add_order_line,
    cancel_order,
    close_order,
    confirm_order,
    create_bulk_orders_from_requisitions,
    create_order,
    create_order_from_requisition,
    mark_order_in_transit,
    mark_order_invoiced,
    mark_order_partially_received,
    mark_order_received,
    open_order_dispute,
    resolve_order_dispute,
    send_order,
    submit_order_for_validation,
    validate_order,
)
from apps.purchase.services.receiving import order_reception_variance, receive_order_line
from apps.purchase.services.reordering import create_reordering_rule, run_reordering
from apps.purchase.services.requisitions import (
    add_requisition_line,
    approve_requisition,
    create_requisition,
    reject_requisition,
    submit_requisition,
)
from apps.purchase.services.rfq import (
    add_rfq_line,
    add_rfq_supplier,
    award_rfq,
    compute_comparison_table,
    create_rfq,
    record_rfq_response,
    send_rfq,
)

router = Router(tags=["purchase"])


class RequisitionLineIn(Schema):
    variant_id: str
    description: str
    qty: Decimal
    uom: str = ""
    preferred_supplier_id: str | None = None


class RequisitionIn(Schema):
    department: str = ""
    date_needed: dt.date
    justification: str = ""
    source_document: str = ""
    lines: list[RequisitionLineIn] = []


class RequisitionRejectIn(Schema):
    reason: str


def _serialize_line(line) -> dict:  # type: ignore[no-untyped-def,type-arg]
    return {
        "id": str(line.id),
        "variant_id": str(line.variant_id),
        "description": line.description,
        "qty": line.qty,
        "uom": line.uom,
        "estimated_price_mga": line.estimated_price_mga,
        "preferred_supplier_id": str(line.preferred_supplier_id)
        if line.preferred_supplier_id
        else None,
    }


def _serialize_requisition(requisition: PurRequisition) -> dict:  # type: ignore[type-arg]
    return {
        "id": str(requisition.id),
        "reference": requisition.reference,
        "requester_id": str(requisition.requester_id),
        "department": requisition.department,
        "date_needed": requisition.date_needed,
        "justification": requisition.justification,
        "state": requisition.state,
        "source_document": requisition.source_document,
        "rejection_reason": requisition.rejection_reason,
        "lines": [_serialize_line(line) for line in requisition.lines.all()],
    }


# NOTE ordre des decorateurs : `@router.xxx` DOIT etre le decorateur EXTERNE
# et `@require_permission(...)` l'INTERNE (juste au-dessus de `def`) — cf.
# `apps.core.services.permissions.require_permission` (bug T6, ne jamais
# inverser).


@router.get("/purchase/requisitions")
@require_permission("purchase.view_purrequisition")
def list_requisitions(request):
    requisitions = PurRequisition.objects.all().order_by("-created_at")
    return {"results": [_serialize_requisition(requisition) for requisition in requisitions]}


@router.post("/purchase/requisitions")
@require_permission("purchase.add_purrequisition")
def create_requisition_endpoint(request, payload: RequisitionIn):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    requisition = create_requisition(
        tenant=tenant,
        requester=request.auth,
        department=payload.department,
        date_needed=payload.date_needed,
        justification=payload.justification,
        source_document=payload.source_document,
    )
    for line in payload.lines:
        add_requisition_line(
            requisition,
            variant_id=uuid.UUID(line.variant_id),
            description=line.description,
            qty=line.qty,
            uom=line.uom,
            preferred_supplier_id=uuid.UUID(line.preferred_supplier_id)
            if line.preferred_supplier_id
            else None,
        )
    requisition.refresh_from_db()
    return _serialize_requisition(requisition)


@router.get("/purchase/requisitions/{requisition_id}")
@require_permission("purchase.view_purrequisition")
def get_requisition_endpoint(request, requisition_id: str):
    requisition = get_object_or_404(PurRequisition, id=requisition_id)
    return _serialize_requisition(requisition)


@router.post("/purchase/requisitions/{requisition_id}/lines")
@require_permission("purchase.change_purrequisition")
def add_requisition_line_endpoint(request, requisition_id: str, payload: RequisitionLineIn):
    requisition = get_object_or_404(PurRequisition, id=requisition_id)
    try:
        add_requisition_line(
            requisition,
            variant_id=uuid.UUID(payload.variant_id),
            description=payload.description,
            qty=payload.qty,
            uom=payload.uom,
            preferred_supplier_id=uuid.UUID(payload.preferred_supplier_id)
            if payload.preferred_supplier_id
            else None,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    requisition.refresh_from_db()
    return _serialize_requisition(requisition)


@router.post("/purchase/requisitions/{requisition_id}/submit")
@require_permission("purchase.change_purrequisition")
def submit_requisition_endpoint(request, requisition_id: str):
    requisition = get_object_or_404(PurRequisition, id=requisition_id)
    try:
        submit_requisition(requisition)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_requisition(requisition)


@router.post("/purchase/requisitions/{requisition_id}/approve")
@require_permission("purchase.change_purrequisition")
def approve_requisition_endpoint(request, requisition_id: str):
    requisition = get_object_or_404(PurRequisition, id=requisition_id)
    try:
        approve_requisition(requisition, approved_by=request.auth)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_requisition(requisition)


@router.post("/purchase/requisitions/{requisition_id}/reject")
@require_permission("purchase.change_purrequisition")
def reject_requisition_endpoint(request, requisition_id: str, payload: RequisitionRejectIn):
    requisition = get_object_or_404(PurRequisition, id=requisition_id)
    try:
        reject_requisition(requisition, reason=payload.reason)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_requisition(requisition)


# ---------------------------------------------------------------------------
# RG-PUR-4 — Appels d'offres (PU3+PU4, cf. plan)
# ---------------------------------------------------------------------------


class RfqLineIn(Schema):
    variant_id: str
    description: str
    qty: Decimal
    uom: str = ""


class RfqIn(Schema):
    date: dt.date
    deadline: dt.date | None = None
    award_criteria: dict | None = None


class RfqSupplierIn(Schema):
    partner_id: str


class RfqResponseLineIn(Schema):
    variant_id: str
    qty: Decimal
    unit_price_mga: Decimal


class RfqResponseIn(Schema):
    partner_id: str
    date_received: dt.date
    lines: list[RfqResponseLineIn] = []
    currency: str = "MGA"
    lead_time_days: int = 0
    validity_date: dt.date | None = None


class RfqAwardIn(Schema):
    response_id: str


def _serialize_rfq_line(line) -> dict:  # type: ignore[no-untyped-def,type-arg]
    return {
        "id": str(line.id),
        "variant_id": str(line.variant_id),
        "description": line.description,
        "qty": line.qty,
        "uom": line.uom,
    }


def _serialize_rfq_response(response: PurRfqResponse) -> dict:  # type: ignore[type-arg]
    return {
        "id": str(response.id),
        "partner_id": str(response.partner_id),
        "date_received": response.date_received,
        "total_mga": response.total_mga,
        "currency": response.currency,
        "lead_time_days": response.lead_time_days,
        "validity_date": response.validity_date,
        "score": response.score,
        "lines": [
            {
                "id": str(line.id),
                "variant_id": str(line.variant_id),
                "qty": line.qty,
                "unit_price_mga": line.unit_price_mga,
            }
            for line in response.lines.all()
        ],
    }


def _serialize_rfq(rfq: PurRfq) -> dict:  # type: ignore[type-arg]
    return {
        "id": str(rfq.id),
        "reference": rfq.reference,
        "date": rfq.date,
        "deadline": rfq.deadline,
        "state": rfq.state,
        "award_criteria": rfq.award_criteria,
        "lines": [_serialize_rfq_line(line) for line in rfq.lines.all()],
        "suppliers": [str(s.partner_id) for s in rfq.suppliers.all()],
        "responses": [_serialize_rfq_response(response) for response in rfq.responses.all()],
    }


@router.get("/purchase/rfqs")
@require_permission("purchase.view_purrfq")
def list_rfqs(request):
    rfqs = PurRfq.objects.all().order_by("-created_at")
    return {"results": [_serialize_rfq(rfq) for rfq in rfqs]}


@router.post("/purchase/rfqs")
@require_permission("purchase.add_purrfq")
def create_rfq_endpoint(request, payload: RfqIn):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    rfq = create_rfq(
        tenant=tenant,
        date=payload.date,
        deadline=payload.deadline,
        award_criteria=payload.award_criteria,
    )
    return _serialize_rfq(rfq)


@router.get("/purchase/rfqs/{rfq_id}")
@require_permission("purchase.view_purrfq")
def get_rfq_endpoint(request, rfq_id: str):
    rfq = get_object_or_404(PurRfq, id=rfq_id)
    return _serialize_rfq(rfq)


@router.post("/purchase/rfqs/{rfq_id}/lines")
@require_permission("purchase.change_purrfq")
def add_rfq_line_endpoint(request, rfq_id: str, payload: RfqLineIn):
    rfq = get_object_or_404(PurRfq, id=rfq_id)
    add_rfq_line(
        rfq,
        variant_id=uuid.UUID(payload.variant_id),
        description=payload.description,
        qty=payload.qty,
        uom=payload.uom,
    )
    rfq.refresh_from_db()
    return _serialize_rfq(rfq)


@router.post("/purchase/rfqs/{rfq_id}/suppliers")
@require_permission("purchase.change_purrfq")
def add_rfq_supplier_endpoint(request, rfq_id: str, payload: RfqSupplierIn):
    rfq = get_object_or_404(PurRfq, id=rfq_id)
    add_rfq_supplier(rfq, partner_id=uuid.UUID(payload.partner_id))
    rfq.refresh_from_db()
    return _serialize_rfq(rfq)


@router.post("/purchase/rfqs/{rfq_id}/send")
@require_permission("purchase.change_purrfq")
def send_rfq_endpoint(request, rfq_id: str):
    rfq = get_object_or_404(PurRfq, id=rfq_id)
    try:
        send_rfq(rfq)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_rfq(rfq)


@router.post("/purchase/rfqs/{rfq_id}/responses")
@require_permission("purchase.change_purrfq")
def record_rfq_response_endpoint(request, rfq_id: str, payload: RfqResponseIn):
    rfq = get_object_or_404(PurRfq, id=rfq_id)
    try:
        record_rfq_response(
            rfq,
            partner_id=uuid.UUID(payload.partner_id),
            date_received=payload.date_received,
            lines=[
                {
                    "variant_id": uuid.UUID(line.variant_id),
                    "qty": line.qty,
                    "unit_price_mga": line.unit_price_mga,
                }
                for line in payload.lines
            ],
            currency=payload.currency,
            lead_time_days=payload.lead_time_days,
            validity_date=payload.validity_date,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    rfq.refresh_from_db()
    return _serialize_rfq(rfq)


@router.get("/purchase/rfqs/{rfq_id}/comparison")
@require_permission("purchase.view_purrfq")
def rfq_comparison_endpoint(request, rfq_id: str):
    rfq = get_object_or_404(PurRfq, id=rfq_id)
    rows = compute_comparison_table(rfq)
    return {
        "results": [
            {
                "response_id": str(row["response_id"]),
                "partner_id": str(row["partner_id"]),
                "total_mga": row["total_mga"],
                "lead_time_days": row["lead_time_days"],
                "validity_date": row["validity_date"],
                "score": row["score"],
            }
            for row in rows
        ]
    }


@router.post("/purchase/rfqs/{rfq_id}/award")
@require_permission("purchase.change_purrfq")
def award_rfq_endpoint(request, rfq_id: str, payload: RfqAwardIn):
    rfq = get_object_or_404(PurRfq, id=rfq_id)
    response = get_object_or_404(PurRfqResponse, id=payload.response_id)
    try:
        order = award_rfq(rfq, response, awarded_by=request.auth)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_order(order)


# ---------------------------------------------------------------------------
# PurOrder — commande d'achat (FSM §5.6.4, PUR-ROUT1, PUR-BULK1, PU3+PU4)
# ---------------------------------------------------------------------------


class OrderLineIn(Schema):
    variant_id: str
    description: str
    qty: Decimal
    unit_price_mga: Decimal
    uom: str = ""
    discount_pct: Decimal = Decimal(0)
    tax_pct: Decimal = Decimal(0)
    supplier_sku: str = ""


class OrderIn(Schema):
    partner_id: str
    date: dt.date
    date_expected: dt.date | None = None
    origin: str = PurOrder.ORIGIN_LOCAL
    currency: str = "MGA"
    incoterm: str = ""
    lines: list[OrderLineIn] = []


class OrderCancelIn(Schema):
    reason: str


class OrderDisputeIn(Schema):
    reason: str


class OrderFromRequisitionIn(Schema):
    partner_id: str


class BulkFromRequisitionsIn(Schema):
    requisition_ids: list[str]


def _serialize_order_line(line) -> dict:  # type: ignore[no-untyped-def,type-arg]
    return {
        "id": str(line.id),
        "sequence": line.sequence,
        "variant_id": str(line.variant_id),
        "supplier_sku": line.supplier_sku,
        "description": line.description,
        "qty": line.qty,
        "uom": line.uom,
        "unit_price_mga": line.unit_price_mga,
        "discount_pct": line.discount_pct,
        "tax_pct": line.tax_pct,
        "subtotal_mga": line.subtotal_mga,
        "qty_received": line.qty_received,
        "qty_invoiced": line.qty_invoiced,
    }


def _serialize_order(order: PurOrder) -> dict:  # type: ignore[type-arg]
    return {
        "id": str(order.id),
        "reference": order.reference,
        "partner_id": str(order.partner_id),
        "date": order.date,
        "date_expected": order.date_expected,
        "currency": order.currency,
        "origin": order.origin,
        "incoterm": order.incoterm,
        "state": order.state,
        "amount_untaxed_mga": order.amount_untaxed_mga,
        "amount_tax_mga": order.amount_tax_mga,
        "amount_total_mga": order.amount_total_mga,
        "requisition_id": str(order.requisition_id) if order.requisition_id else None,
        "rfq_id": str(order.rfq_id) if order.rfq_id else None,
        "cancel_reason": order.cancel_reason,
        "dispute_reason": order.dispute_reason,
        "lines": [_serialize_order_line(line) for line in order.lines.all()],
    }


def _handle_order_errors(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
    try:
        return fn(*args, **kwargs), None
    except (ValidationError, PurchaseApprovalRequiredError, TransitionPermissionError) as exc:
        message = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
        return None, JsonResponse({"detail": message}, status=400)


@router.get("/purchase/orders")
@require_permission("purchase.view_purorder")
def list_orders(request):
    orders = PurOrder.objects.all().order_by("-created_at")
    return {"results": [_serialize_order(order) for order in orders]}


@router.post("/purchase/orders")
@require_permission("purchase.add_purorder")
def create_order_endpoint(request, payload: OrderIn):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    order = create_order(
        tenant=tenant,
        partner_id=uuid.UUID(payload.partner_id),
        date=payload.date,
        date_expected=payload.date_expected,
        origin=payload.origin,
        currency=payload.currency,
        incoterm=payload.incoterm,
    )
    for line in payload.lines:
        add_order_line(
            order,
            variant_id=uuid.UUID(line.variant_id),
            description=line.description,
            qty=line.qty,
            unit_price_mga=line.unit_price_mga,
            uom=line.uom,
            discount_pct=line.discount_pct,
            tax_pct=line.tax_pct,
            supplier_sku=line.supplier_sku,
        )
    order.refresh_from_db()
    return _serialize_order(order)


@router.post("/purchase/orders/from-requisition/{requisition_id}")
@require_permission("purchase.add_purorder")
def create_order_from_requisition_endpoint(
    request, requisition_id: str, payload: OrderFromRequisitionIn
):
    requisition = get_object_or_404(PurRequisition, id=requisition_id)
    try:
        order = create_order_from_requisition(requisition, partner_id=uuid.UUID(payload.partner_id))
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_order(order)


@router.post("/purchase/orders/bulk-from-requisitions")
@require_permission("purchase.add_purorder")
def bulk_from_requisitions_endpoint(request, payload: BulkFromRequisitionsIn):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    try:
        result = create_bulk_orders_from_requisitions(
            [uuid.UUID(rid) for rid in payload.requisition_ids], tenant=tenant
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return {
        "orders_created": [_serialize_order(order) for order in result["orders_created"]],
        "lines_skipped": [
            {
                "requisition_id": str(item["requisition_id"]),
                "line_id": str(item["line_id"]),
                "description": item["description"],
                "reason": item["reason"],
            }
            for item in result["lines_skipped"]
        ],
    }


@router.get("/purchase/orders/{order_id}")
@require_permission("purchase.view_purorder")
def get_order_endpoint(request, order_id: str):
    order = get_object_or_404(PurOrder, id=order_id)
    return _serialize_order(order)


@router.post("/purchase/orders/{order_id}/lines")
@require_permission("purchase.change_purorder")
def add_order_line_endpoint(request, order_id: str, payload: OrderLineIn):
    order = get_object_or_404(PurOrder, id=order_id)
    try:
        add_order_line(
            order,
            variant_id=uuid.UUID(payload.variant_id),
            description=payload.description,
            qty=payload.qty,
            unit_price_mga=payload.unit_price_mga,
            uom=payload.uom,
            discount_pct=payload.discount_pct,
            tax_pct=payload.tax_pct,
            supplier_sku=payload.supplier_sku,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    order.refresh_from_db()
    return _serialize_order(order)


@router.post("/purchase/orders/{order_id}/submit")
@require_permission("purchase.change_purorder")
def submit_order_endpoint(request, order_id: str):
    order = get_object_or_404(PurOrder, id=order_id)
    result, error = _handle_order_errors(submit_order_for_validation, order, request.auth)
    if error is not None:
        return error
    return _serialize_order(result)


@router.post("/purchase/orders/{order_id}/validate")
@require_permission("purchase.change_purorder")
def validate_order_endpoint(request, order_id: str):
    order = get_object_or_404(PurOrder, id=order_id)
    result, error = _handle_order_errors(validate_order, order, request.auth)
    if error is not None:
        return error
    return _serialize_order(result)


@router.post("/purchase/orders/{order_id}/send")
@require_permission("purchase.change_purorder")
def send_order_endpoint(request, order_id: str):
    order = get_object_or_404(PurOrder, id=order_id)
    result, error = _handle_order_errors(send_order, order, request.auth)
    if error is not None:
        return error
    return _serialize_order(result)


@router.post("/purchase/orders/{order_id}/confirm")
@require_permission("purchase.change_purorder")
def confirm_order_endpoint(request, order_id: str):
    order = get_object_or_404(PurOrder, id=order_id)
    result, error = _handle_order_errors(confirm_order, order, request.auth)
    if error is not None:
        return error
    return _serialize_order(result)


@router.post("/purchase/orders/{order_id}/in-transit")
@require_permission("purchase.change_purorder")
def mark_order_in_transit_endpoint(request, order_id: str):
    order = get_object_or_404(PurOrder, id=order_id)
    result, error = _handle_order_errors(mark_order_in_transit, order, request.auth)
    if error is not None:
        return error
    return _serialize_order(result)


@router.post("/purchase/orders/{order_id}/partially-receive")
@require_permission("purchase.change_purorder")
def mark_order_partially_received_endpoint(request, order_id: str):
    order = get_object_or_404(PurOrder, id=order_id)
    result, error = _handle_order_errors(mark_order_partially_received, order, request.auth)
    if error is not None:
        return error
    return _serialize_order(result)


@router.post("/purchase/orders/{order_id}/receive")
@require_permission("purchase.change_purorder")
def mark_order_received_endpoint(request, order_id: str):
    order = get_object_or_404(PurOrder, id=order_id)
    result, error = _handle_order_errors(mark_order_received, order, request.auth)
    if error is not None:
        return error
    return _serialize_order(result)


@router.post("/purchase/orders/{order_id}/invoice")
@require_permission("purchase.change_purorder")
def mark_order_invoiced_endpoint(request, order_id: str):
    order = get_object_or_404(PurOrder, id=order_id)
    result, error = _handle_order_errors(mark_order_invoiced, order, request.auth)
    if error is not None:
        return error
    return _serialize_order(result)


@router.post("/purchase/orders/{order_id}/close")
@require_permission("purchase.change_purorder")
def close_order_endpoint(request, order_id: str):
    order = get_object_or_404(PurOrder, id=order_id)
    result, error = _handle_order_errors(close_order, order, request.auth)
    if error is not None:
        return error
    return _serialize_order(result)


@router.post("/purchase/orders/{order_id}/cancel")
@require_permission("purchase.change_purorder")
def cancel_order_endpoint(request, order_id: str, payload: OrderCancelIn):
    order = get_object_or_404(PurOrder, id=order_id)
    result, error = _handle_order_errors(cancel_order, order, request.auth, reason=payload.reason)
    if error is not None:
        return error
    return _serialize_order(result)


@router.post("/purchase/orders/{order_id}/dispute")
@require_permission("purchase.change_purorder")
def open_order_dispute_endpoint(request, order_id: str, payload: OrderDisputeIn):
    order = get_object_or_404(PurOrder, id=order_id)
    result, error = _handle_order_errors(
        open_order_dispute, order, request.auth, reason=payload.reason
    )
    if error is not None:
        return error
    return _serialize_order(result)


@router.post("/purchase/orders/{order_id}/resolve-dispute")
@require_permission("purchase.change_purorder")
def resolve_order_dispute_endpoint(request, order_id: str):
    order = get_object_or_404(PurOrder, id=order_id)
    result, error = _handle_order_errors(resolve_order_dispute, order, request.auth)
    if error is not None:
        return error
    return _serialize_order(result)


# ---------------------------------------------------------------------------
# RG-PUR-5 — Reception (PU5, cf. plan)
# ---------------------------------------------------------------------------


class ReceiveLineIn(Schema):
    qty_received_now: Decimal
    quality_status: str
    notes: str = ""
    photo_document_ids: list[str] = []


@router.post("/purchase/orders/{order_id}/lines/{line_id}/receive")
@require_permission("purchase.change_purorder")
def receive_order_line_endpoint(request, order_id: str, line_id: str, payload: ReceiveLineIn):
    line = get_object_or_404(PurOrderLine, id=line_id, order_id=order_id)
    try:
        receive_order_line(
            line,
            qty_received_now=payload.qty_received_now,
            quality_status=payload.quality_status,
            user=request.auth,
            notes=payload.notes,
            photo_document_ids=[uuid.UUID(doc_id) for doc_id in payload.photo_document_ids],
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    order = get_object_or_404(PurOrder, id=order_id)
    return _serialize_order(order)


@router.get("/purchase/orders/{order_id}/reception-variance")
@require_permission("purchase.view_purorder")
def order_reception_variance_endpoint(request, order_id: str):
    order = get_object_or_404(PurOrder, id=order_id)
    rows = order_reception_variance(order)
    return {
        "results": [
            {
                "line_id": str(row["line_id"]),
                "variant_id": str(row["variant_id"]),
                "description": row["description"],
                "qty_ordered": row["qty_ordered"],
                "qty_received": row["qty_received"],
                "variance": row["variance"],
                "variance_pct": row["variance_pct"],
            }
            for row in rows
        ]
    }


# ---------------------------------------------------------------------------
# RG-PUR-3 — Reapprovisionnement automatique (PU5, cf. plan)
# ---------------------------------------------------------------------------


class ReorderingRuleIn(Schema):
    variant_id: str
    min_qty: Decimal
    max_qty: Decimal
    multiple_qty: Decimal = Decimal(1)
    lead_time_days: int = 0
    warehouse_id: str | None = None


def _serialize_reordering_rule(rule: PurReorderingRule) -> dict:  # type: ignore[type-arg]
    return {
        "id": str(rule.id),
        "variant_id": str(rule.variant_id),
        "warehouse_id": str(rule.warehouse_id) if rule.warehouse_id else None,
        "min_qty": rule.min_qty,
        "max_qty": rule.max_qty,
        "multiple_qty": rule.multiple_qty,
        "lead_time_days": rule.lead_time_days,
        "is_active": rule.is_active,
    }


@router.get("/purchase/reordering-rules")
@require_permission("purchase.view_purreorderingrule")
def list_reordering_rules(request):
    rules = PurReorderingRule.objects.all().order_by("-created_at")
    return {"results": [_serialize_reordering_rule(rule) for rule in rules]}


@router.post("/purchase/reordering-rules")
@require_permission("purchase.add_purreorderingrule")
def create_reordering_rule_endpoint(request, payload: ReorderingRuleIn):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    rule = create_reordering_rule(
        tenant=tenant,
        variant_id=uuid.UUID(payload.variant_id),
        min_qty=payload.min_qty,
        max_qty=payload.max_qty,
        multiple_qty=payload.multiple_qty,
        lead_time_days=payload.lead_time_days,
        warehouse_id=uuid.UUID(payload.warehouse_id) if payload.warehouse_id else None,
    )
    return _serialize_reordering_rule(rule)


@router.post("/purchase/reordering/run")
@require_permission("purchase.run_reordering")
def run_reordering_endpoint(request):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    requisitions = run_reordering(tenant)
    return {"results": [_serialize_requisition(requisition) for requisition in requisitions]}
