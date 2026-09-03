"""Ecrans HTMX minimaux du module `crm` (U1) : liste des opportunites
(scopee RG-CRM-5), detail avec bandeau d'etape + chronologie des
activites, saisie rapide. Meme patron que `apps.accounting.views`."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.models.user import User
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant
from apps.crm.models import CrmLead, CrmLostReason, CrmPipeline, CrmStage, CrmTeam
from apps.crm.services.activities import lead_timeline, log_activity
from apps.crm.services.discounts import DiscountApprovalRequiredError, enforce_discount_threshold
from apps.crm.services.leads import add_lead_line, create_lead_quick
from apps.crm.services.pipeline import move_lead_to_stage
from apps.crm.services.pipelines import resolve_default_pipeline
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
    # RG-CRM-5 (CRM-6 du cahier des charges) : correctif d'un manque reel —
    # cette vue recuperait le lead SANS repasser par
    # `scope_leads_for_user`, contrairement a `lead_list` juste au-dessus.
    # Consequence avant ce correctif : n'importe quel utilisateur
    # authentifie du tenant (pas seulement le vendeur assigne ou son
    # equipe) pouvait consulter ET agir (changer d'etape, ajouter une
    # activite/ligne) sur N'IMPORTE QUEL lead par simple connaissance de
    # son UUID. `get_object_or_404` sur le queryset deja scope reproduit le
    # meme comportement "objet inexistant" (404) qu'un ID invalide plutot
    # que de distinguer "n'existe pas" de "existe mais hors portee" —
    # coherent avec le choix deja fait sur les bulletins de paie (RG-PAY-9)
    # de ne jamais laisser deviner l'existence d'un enregistrement d'autrui.
    lead = get_object_or_404(scope_leads_for_user(CrmLead.objects.filter(is_active=True), request.user), id=lead_id)
    user = cast(User, request.user)
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
            elif action == "add_line":
                variant_id_raw = request.POST.get("variant_id", "").strip()
                unit_price_raw = request.POST.get("unit_price", "").strip()
                line = add_lead_line(
                    lead,
                    description=request.POST.get("description", ""),
                    variant_id=uuid.UUID(variant_id_raw) if variant_id_raw else None,
                    qty=Decimal(request.POST.get("qty") or "1"),
                    unit_price=Decimal(unit_price_raw) if unit_price_raw else None,
                    discount_pct=Decimal(request.POST.get("discount_pct") or "0"),
                    is_custom=bool(request.POST.get("is_custom")),
                )
                enforce_discount_threshold(line, requested_by=user)
        except (
            ValidationError,
            DiscountApprovalRequiredError,
            InvalidOperation,
            ValueError,
        ) as exc:
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
            "lines": lead.lines.all(),
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
            partner_id_raw = request.POST.get("partner_id", "").strip()
            pipeline_id_raw = request.POST.get("pipeline", "").strip()
            team_id_raw = request.POST.get("team", "").strip()
            revenue_raw = request.POST.get("expected_revenue_mga", "").strip()
            close_date_raw = request.POST.get("expected_close_date", "").strip()
            priority = request.POST.get("priority", "").strip()

            extra: dict[str, object] = {}
            if team_id_raw:
                extra["team_id"] = uuid.UUID(team_id_raw)
            if revenue_raw:
                extra["expected_revenue_mga"] = Decimal(revenue_raw)
            if close_date_raw:
                extra["expected_close_date"] = date.fromisoformat(close_date_raw)
            if priority:
                extra["priority"] = priority
            for field in ("source", "contact_name", "email", "phone", "description"):
                value = request.POST.get(field, "").strip()
                if value:
                    extra[field] = value

            pipeline = (
                get_object_or_404(CrmPipeline, id=pipeline_id_raw) if pipeline_id_raw else None
            )

            lead = create_lead_quick(
                tenant=tenant,
                name=request.POST.get("name", ""),
                partner_id=uuid.UUID(partner_id_raw) if partner_id_raw else None,
                pipeline=pipeline,
                **extra,
            )
        except (ValueError, InvalidOperation) as exc:
            error = str(exc)
        else:
            return redirect("crm:detail", lead_id=lead.id)

    default_pipeline = resolve_default_pipeline(tenant)
    return render(
        request,
        "crm/create.html",
        {
            "error": error,
            "pipelines": CrmPipeline.objects.filter(tenant=tenant),
            "default_pipeline_id": default_pipeline.id if default_pipeline else None,
            "teams": CrmTeam.objects.filter(tenant=tenant),
            "priority_choices": CrmLead.PRIORITY_CHOICES,
        },
    )
