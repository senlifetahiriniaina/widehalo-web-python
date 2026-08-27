"""API django-ninja du module `purchase` (§5.6.6) — PU1 : demande d'achat
(`PurRequisition`/`PurRequisitionLine`), creation/listing, ajout de
lignes, et workflow `draft -> submitted -> approved/rejected`."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from apps.core.services.permissions import require_permission
from apps.purchase.models import PurRequisition
from apps.purchase.services.requisitions import (
    add_requisition_line,
    approve_requisition,
    create_requisition,
    reject_requisition,
    submit_requisition,
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
