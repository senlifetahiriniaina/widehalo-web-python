"""Ecrans HTMX minimaux du module `crm` (U1) : liste des opportunites
(scopee RG-CRM-5), detail avec bandeau d'etape + chronologie des
activites, saisie rapide. Meme patron que `apps.accounting.views`."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant
from apps.crm.models import CrmLead, CrmLostReason, CrmStage
from apps.crm.services.activities import lead_timeline, log_activity
from apps.crm.services.leads import create_lead_quick
from apps.crm.services.pipeline import move_lead_to_stage
from apps.crm.services.scoping import scope_leads_for_user
from apps.crm.services.scoring import compute_lead_score, whatsapp_contact_link

COLUMNS = [
    Column(key="reference", label="Reference"),
    Column(key="name", label="Nom"),
    Column(key="stage", label="Etape"),
    Column(key="expected_revenue_mga", label="Montant attendu (MGA)", searchable=False),
]


@login_required
def lead_list(request: HttpRequest) -> HttpResponse:
    queryset = scope_leads_for_user(CrmLead.objects.filter(is_active=True), request.user)
    return smart_table_response(
        request,
        table_key="crm.leads",
        columns=COLUMNS,
        queryset=queryset,
        page_template="crm/list.html",
        page_context={"row_url_name": "crm:detail"},
    )


@login_required
def lead_detail(request: HttpRequest, lead_id: str) -> HttpResponse:
    lead = get_object_or_404(CrmLead, id=lead_id)
    error = None

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "move_stage":
                stage = get_object_or_404(CrmStage, id=request.POST.get("stage_id"))
                lost_reason_id = request.POST.get("lost_reason_id")
                lost_reason = (
                    get_object_or_404(CrmLostReason, id=lost_reason_id) if lost_reason_id else None
                )
                move_lead_to_stage(
                    lead, stage, lost_reason=lost_reason, comment=request.POST.get("comment", "")
                )
            elif action == "log_activity":
                log_activity(
                    lead,
                    activity_type=request.POST.get("activity_type", "call"),
                    subject=request.POST.get("subject", ""),
                    notes=request.POST.get("notes", ""),
                )
        except ValidationError as exc:
            error = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        else:
            return redirect("crm:detail", lead_id=lead.id)

    return render(
        request,
        "crm/detail.html",
        {
            "lead": lead,
            "stages": lead.pipeline.stages.all(),
            "lost_reasons": CrmLostReason.objects.filter(tenant=lead.tenant),
            "activities": lead_timeline(lead),
            "score": compute_lead_score(lead),
            "whatsapp_link": whatsapp_contact_link(lead),
            "error": error,
        },
    )


@login_required
def lead_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            lead = create_lead_quick(tenant=tenant, name=request.POST.get("name", ""))
        except ValueError as exc:
            error = str(exc)
        else:
            return redirect("crm:detail", lead_id=lead.id)

    return render(request, "crm/create.html", {"error": error})
