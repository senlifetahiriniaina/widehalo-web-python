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
from django.utils.translation import gettext_lazy as _

from apps.core.models.user import User
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant
from apps.feasibility.models import SECTOR_CHOICES, FeaStudy, FeaStudyLine
from apps.feasibility.services.simulation import (
    add_study_line,
    complete_study,
    create_study,
    simulate_study_line,
)

WIZARD_STEP_LABELS = [_("En-tête"), _("Lignes"), _("Simulation")]


def _add_line_from_post(study: FeaStudy, request: HttpRequest) -> None:
    """Glue partagee entre l'ecran detail (action `add_line`) et l'etape 2
    de l'assistant guide (UXR6) — meme lecture du POST, meme appel a
    `add_study_line` deja existant, aucune reimplementation."""
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


def _simulate_line_from_post(request: HttpRequest) -> FeaStudyLine:
    """Glue partagee entre l'ecran detail (action `simulate_line`) et
    l'etape 3 de l'assistant guide (UXR6) — meme appel a
    `simulate_study_line` deja existant, aucune reimplementation."""
    line = get_object_or_404(FeaStudyLine, id=request.POST.get("line_id"))
    return simulate_study_line(
        line,
        overhead_rate_pct=Decimal(request.POST.get("overhead_rate_pct", "0")),
    )


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
def study_wizard_step1(request: HttpRequest) -> HttpResponse:
    """Etape 1 de l'assistant guide (UXR6) : en-tete de l'etude. Meme
    formulaire/logique que l'ancien ecran `feasibility:create` (`name`/
    `sector_code`/`description`, appel direct a `create_study` deja
    existant — aucune nouvelle logique metier), mais redirige vers l'etape
    2 de l'assistant au lieu du detail directement."""
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
            return redirect("feasibility:wizard_step2", study_id=study.id)
        except ValidationError as exc:
            error = str(exc)
    return render(
        request,
        "feasibility/wizard_step1.html",
        {
            "error": error,
            "sectors": SECTOR_CHOICES,
            "wizard_current_step": 1,
            "wizard_steps": WIZARD_STEP_LABELS,
        },
    )


@login_required
def study_wizard_step2(request: HttpRequest, study_id: str) -> HttpResponse:
    """Etape 2 de l'assistant guide (UXR6) : ajout de lignes. Reutilise TEL
    QUEL `add_study_line` (meme appel que l'action `add_line` de l'ecran
    detail existant, cf. `study_detail`) — aucune nouvelle logique metier,
    uniquement la coquille de navigation guidee."""
    study = get_object_or_404(FeaStudy, id=study_id)
    error = None

    if request.method == "POST":
        try:
            _add_line_from_post(study, request)
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = str(exc)

    lines = study.lines.all()
    return render(
        request,
        "feasibility/wizard_step2.html",
        {
            "study": study,
            "lines": lines,
            "error": error,
            "wizard_current_step": 2,
            "wizard_steps": WIZARD_STEP_LABELS,
        },
    )


@login_required
def study_wizard_step3(request: HttpRequest, study_id: str) -> HttpResponse:
    """Etape 3 de l'assistant guide (UXR6) : simulation + revue, puis
    finalisation. Reutilise TEL QUEL `simulate_study_line` (action
    "Simuler" par ligne, identique a l'action `simulate_line` de l'ecran
    detail existant) et `complete_study` (bouton final "Terminer",
    JUSQU'ICI JAMAIS CABLE a un ecran — c'est le point d'entree que ce
    chantier de navigation vient cabler, cf. docstring de
    `complete_study`). Grille cote serveur : etape 3 avec 0 ligne renvoie
    vers l'etape 2 (jamais fiee au seul JS cote client)."""
    study = get_object_or_404(FeaStudy, id=study_id)

    if not study.lines.exists():
        return redirect("feasibility:wizard_step2", study_id=study.id)

    error = None
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "simulate_line":
                _simulate_line_from_post(request)
            elif action == "complete":
                complete_study(study)
                return redirect("feasibility:detail", study_id=study.id)
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = str(exc)

    lines = study.lines.all()
    return render(
        request,
        "feasibility/wizard_step3.html",
        {
            "study": study,
            "lines": lines,
            "error": error,
            "total_cost_mga": study.total_cost_mga(),
            "total_revenue_mga": study.total_revenue_mga(),
            "wizard_current_step": 3,
            "wizard_steps": WIZARD_STEP_LABELS,
        },
    )


@login_required
def study_detail(request: HttpRequest, study_id: str) -> HttpResponse:
    study = get_object_or_404(FeaStudy, id=study_id)
    error = None

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "add_line":
                _add_line_from_post(study, request)
            elif action == "simulate_line":
                _simulate_line_from_post(request)
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
