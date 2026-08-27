"""Ecrans HTMX minimaux du module `patronage` (U1) : liste des patrons,
detail avec pieces/mesures gradees + lien de telechargement du dossier
technique, formulaire de creation. Meme patron que `apps.accounting.views`."""

from __future__ import annotations

from typing import cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.models.user import User
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant
from apps.patronage.models import PatPattern, PatSizeChart
from apps.patronage.services.eco import EcoApprovalRequiredError, validate_pattern_version
from apps.patronage.services.grading import apply_grading
from apps.patronage.services.patterns import create_pattern

COLUMNS = [
    Column(key="code", label="Code"),
    Column(key="name", label="Nom"),
    Column(key="version", label="Version", searchable=False),
    Column(key="state", label="Statut"),
]


@login_required
def pattern_list(request: HttpRequest) -> HttpResponse:
    queryset = PatPattern.objects.filter(is_active=True)
    return smart_table_response(
        request,
        table_key="patronage.patterns",
        columns=COLUMNS,
        queryset=queryset,
        page_template="patronage/list.html",
        page_context={"row_url_name": "patronage:detail"},
    )


@login_required
def pattern_detail(request: HttpRequest, pattern_id: str) -> HttpResponse:
    pattern = get_object_or_404(PatPattern, id=pattern_id)
    user = cast(User, request.user)
    error = None

    if request.method == "POST" and request.POST.get("action") == "validate":
        try:
            validate_pattern_version(pattern, requested_by=user)
        except EcoApprovalRequiredError as exc:
            error = str(exc)
        else:
            return redirect("patronage:detail", pattern_id=pattern.id)

    graded = None
    try:
        graded = apply_grading(pattern.size_chart)
    except ValidationError:
        graded = None

    return render(
        request,
        "patronage/detail.html",
        {
            "pattern": pattern,
            "pieces": pattern.pieces.all(),
            "graded": graded,
            "error": error,
        },
    )


@login_required
def pattern_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    size_charts = PatSizeChart.objects.filter(tenant=tenant)
    error = None

    if request.method == "POST":
        try:
            size_chart = get_object_or_404(PatSizeChart, id=request.POST.get("size_chart_id"))
            pattern = create_pattern(
                tenant=tenant,
                code=request.POST.get("code", ""),
                name=request.POST.get("name", ""),
                size_chart=size_chart,
            )
        except ValidationError as exc:
            error = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        else:
            return redirect("patronage:detail", pattern_id=pattern.id)

    return render(request, "patronage/create.html", {"size_charts": size_charts, "error": error})
