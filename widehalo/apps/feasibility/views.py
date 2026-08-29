"""Ecrans HTMX minimaux du module `feasibility` (FEA1-3) : liste des etudes
(SmartTable), detail (lignes + simulation), creation. Meme patron que
`apps.strategy.views` : chaque vue appelle directement les fonctions de
service, jamais l'API ninja."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import cast
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.models.user import User
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant
from apps.feasibility.models import SECTOR_CHOICES, FeaStudy, FeaStudyLine
from apps.feasibility.services.simulation import add_study_line, create_study, simulate_study_line

COLUMNS = [
    Column(key="reference", label="Reference"),
    Column(key="name", label="Nom"),
    Column(key="sector_code", label="Secteur"),
    Column(key="status", label="Statut", searchable=False),
]


@login_required
def study_list(request: HttpRequest) -> HttpResponse:
    queryset = FeaStudy.objects.filter(is_active=True)
    return smart_table_response(
        request,
        table_key="feasibility.studies",
        columns=COLUMNS,
        queryset=queryset,
        page_template="feasibility/list.html",
        page_context={"row_url_name": "feasibility:detail"},
    )


@login_required
def study_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    user = cast(User, request.user)
    error = None
    if request.method == "POST":
        try:
            study = create_study(
                tenant,
                name=request.POST.get("name", ""),
                description=request.POST.get("description", ""),
                sector_code=request.POST.get("sector_code", ""),
                owner=user,
                created_by=user,
            )
            return redirect("feasibility:detail", study_id=study.id)
        except ValidationError as exc:
            error = str(exc)
    return render(
        request,
        "feasibility/create.html",
        {"error": error, "sectors": SECTOR_CHOICES},
    )


@login_required
def study_detail(request: HttpRequest, study_id: str) -> HttpResponse:
    study = get_object_or_404(FeaStudy, id=study_id)
    error = None

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "add_line":
                raw_variant_id = request.POST.get("variant_id")
                add_study_line(
                    study,
                    variant_id=UUID(raw_variant_id) if raw_variant_id else None,
                    hypothetical_spec={"name": request.POST.get("hypothetical_name", "")}
                    if request.POST.get("hypothetical_name")
                    else {},
                    assumed_qty=Decimal(request.POST.get("assumed_qty", "1")),
                    assumed_unit_price_mga=Decimal(request.POST.get("assumed_unit_price_mga", "0")),
                )
            elif action == "simulate_line":
                line = get_object_or_404(FeaStudyLine, id=request.POST.get("line_id"))
                simulate_study_line(
                    line,
                    overhead_rate_pct=Decimal(request.POST.get("overhead_rate_pct", "0")),
                )
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = str(exc)

    lines = study.lines.all()
    return render(
        request,
        "feasibility/detail.html",
        {
            "study": study,
            "lines": lines,
            "error": error,
            "total_cost_mga": study.total_cost_mga(),
            "total_revenue_mga": study.total_revenue_mga(),
        },
    )
