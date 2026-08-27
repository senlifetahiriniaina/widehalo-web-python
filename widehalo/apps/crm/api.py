"""API django-ninja du module CRM (§5.2). Endpoints OCR/devis/proforma
(CRM-DEVIS/CRM-PROF) explicitement absents — dependent de `sales`, cf.
plan."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from apps.core.services.permissions import require_permission
from apps.crm.models import CrmActivity, CrmLead, CrmLostReason, CrmPipeline, CrmStage
from apps.crm.services.activities import complete_activity, lead_timeline, log_activity
from apps.crm.services.discounts import DiscountApprovalRequiredError, enforce_discount_threshold
from apps.crm.services.leads import create_lead_quick
from apps.crm.services.pipeline import move_lead_to_stage
from apps.crm.services.reports import (
    activity_breakdown,
    conversion_rate,
    lost_reason_breakdown,
    pipeline_breakdown,
    rows_to_bytes,
)
from apps.crm.services.scoping import scope_leads_for_user
from apps.crm.services.scoring import compute_lead_score, whatsapp_contact_link

router = Router(tags=["crm"])


class LeadLineIn(Schema):
    variant_id: str | None = None
    description: str = ""
    qty: Decimal = Decimal(1)
    unit_price: Decimal | None = None
    discount_pct: Decimal = Decimal(0)
    is_custom: bool = False


class LeadIn(Schema):
    name: str
    partner_id: str | None = None
    pipeline_id: str | None = None
    contact_name: str = ""
    email: str = ""
    phone: str = ""
    expected_revenue_mga: Decimal = Decimal(0)
    lines: list[LeadLineIn] = []


class MoveStageIn(Schema):
    stage_id: str
    lost_reason_id: str | None = None
    comment: str = ""


class ActivityIn(Schema):
    activity_type: str
    subject: str
    notes: str = ""


def _serialize_lead(lead: CrmLead) -> dict[str, Any]:
    return {
        "id": str(lead.id),
        "reference": lead.reference,
        "name": lead.name,
        "stage": lead.stage.code,
        "pipeline_id": str(lead.pipeline_id),
        "probability": lead.probability,
        "expected_revenue_mga": str(lead.expected_revenue_mga),
        "score": compute_lead_score(lead),
        "whatsapp_link": whatsapp_contact_link(lead),
    }


# NOTE ordre des decorateurs : `@router.xxx` DOIT etre le decorateur
# EXTERNE et `@require_permission(...)` l'INTERNE (juste au-dessus de
# `def`) — `Router.api_operation` enregistre dans sa table de routage la
# fonction qui lui est passee directement puis la retourne inchangee, donc
# seul le decorateur le plus proche de `def` finit reellement invoque a
# chaque requete (verifie empiriquement : l'ordre inverse ne bloque JAMAIS
# aucune requete HTTP reelle malgre un `_required_permission` visible au
# niveau du nom de fonction).
@router.get("/crm/leads")
@require_permission("crm.view_crmlead")
def list_leads(request):
    leads = scope_leads_for_user(CrmLead.objects.all(), request.auth)
    return {"results": [_serialize_lead(lead) for lead in leads.order_by("-created_at")]}


@router.post("/crm/leads")
@require_permission("crm.add_crmlead")
def create_lead_endpoint(request, payload: LeadIn):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    pipeline = (
        get_object_or_404(CrmPipeline, id=payload.pipeline_id) if payload.pipeline_id else None
    )
    lines = [
        {
            "variant_id": uuid.UUID(line.variant_id) if line.variant_id else None,
            "description": line.description,
            "qty": line.qty,
            "unit_price": line.unit_price,
            "discount_pct": line.discount_pct,
            "is_custom": line.is_custom,
        }
        for line in payload.lines
    ]
    lead = create_lead_quick(
        tenant=tenant,
        name=payload.name,
        partner_id=uuid.UUID(payload.partner_id) if payload.partner_id else None,
        pipeline=pipeline,
        salesperson=request.auth,
        contact_name=payload.contact_name,
        email=payload.email,
        phone=payload.phone,
        expected_revenue_mga=payload.expected_revenue_mga,
        lines=lines,
    )
    return _serialize_lead(lead)


@router.post("/crm/leads/{lead_id}/move-stage")
@require_permission("crm.change_crmlead")
def move_lead_stage_endpoint(request, lead_id: str, payload: MoveStageIn):
    lead = get_object_or_404(CrmLead, id=lead_id)
    stage = get_object_or_404(CrmStage, id=payload.stage_id)
    lost_reason = (
        get_object_or_404(CrmLostReason, id=payload.lost_reason_id)
        if payload.lost_reason_id
        else None
    )
    try:
        moved = move_lead_to_stage(lead, stage, lost_reason=lost_reason, comment=payload.comment)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_lead(moved)


@router.post("/crm/leads/{lead_id}/lines/{line_id}/enforce-discount")
@require_permission("crm.change_crmlead")
def enforce_discount_endpoint(request, lead_id: str, line_id: str):
    lead = get_object_or_404(CrmLead, id=lead_id)
    line = get_object_or_404(lead.lines, id=line_id)
    try:
        enforce_discount_threshold(line, requested_by=request.auth)
    except DiscountApprovalRequiredError as exc:
        return JsonResponse({"detail": str(exc), "status": "pending_approval"}, status=202)
    return {"status": "ok"}


@router.get("/crm/leads/{lead_id}/activities")
@require_permission("crm.view_crmactivity")
def list_lead_activities(request, lead_id: str):
    lead = get_object_or_404(CrmLead, id=lead_id)
    return {
        "results": [
            {
                "id": str(a.id),
                "activity_type": a.activity_type,
                "subject": a.subject,
                "due_at": a.due_at,
                "done_at": a.done_at,
            }
            for a in lead_timeline(lead)
        ]
    }


@router.post("/crm/leads/{lead_id}/activities")
@require_permission("crm.add_crmactivity")
def create_lead_activity_endpoint(request, lead_id: str, payload: ActivityIn):
    lead = get_object_or_404(CrmLead, id=lead_id)
    activity = log_activity(
        lead,
        activity_type=payload.activity_type,
        subject=payload.subject,
        notes=payload.notes,
        assigned_to=request.auth,
    )
    return {"id": str(activity.id)}


@router.post("/crm/activities/{activity_id}/complete")
@require_permission("crm.change_crmactivity")
def complete_activity_endpoint(request, activity_id: str):
    activity = get_object_or_404(CrmActivity, id=activity_id)
    completed = complete_activity(activity)
    return {"id": str(completed.id), "done_at": completed.done_at}


@router.get("/crm/reports/pipeline")
@require_permission("crm.view_crmpipeline")
def pipeline_report_endpoint(request, pipeline_id: str, format: str = "json"):
    pipeline = get_object_or_404(CrmPipeline, id=pipeline_id)
    rows = pipeline_breakdown(pipeline)
    data = rows_to_bytes(
        rows,
        ["stage_code", "stage_name", "lead_count", "total_expected_revenue_mga"],
        format=format,
    )
    return _report_response(data, format)


@router.get("/crm/reports/conversion")
@require_permission("crm.view_crmpipeline")
def conversion_report_endpoint(request, pipeline_id: str):
    pipeline = get_object_or_404(CrmPipeline, id=pipeline_id)
    return conversion_rate(pipeline)


@router.get("/crm/reports/activities")
@require_permission("crm.view_crmactivity")
def activities_report_endpoint(request, format: str = "json"):
    rows = activity_breakdown()
    data = rows_to_bytes(rows, ["activity_type", "count"], format=format)
    return _report_response(data, format)


# crm.view_crmlead choisi plutot que crm.view_crmlostreason : le rapport
# agrege des donnees de leads (lead_count, montant), la ventilation par
# motif de perte n'etant qu'un axe de regroupement.
@router.get("/crm/reports/lost")
@require_permission("crm.view_crmlead")
def lost_report_endpoint(request, format: str = "json"):
    rows = lost_reason_breakdown()
    data = rows_to_bytes(
        rows, ["lost_reason", "lead_count", "total_expected_revenue_mga"], format=format
    )
    return _report_response(data, format)


def _report_response(data: bytes, format: str) -> HttpResponse:
    content_type = {
        "json": "application/json",
        "csv": "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }[format]
    return HttpResponse(data, content_type=content_type)
