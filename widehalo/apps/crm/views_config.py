"""Ecrans de configuration/master-data du module `crm` (U3), regroupes
sous le hub "Parametres" (cf. decision de placement, plan Lot 2)."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext as _

from apps.core.models.user import User
from apps.core.views.tenant_web import resolve_tenant
from apps.crm.models import CrmLostReason, CrmPipeline, CrmStage, CrmTeam


@login_required
def config_index(request: HttpRequest) -> HttpResponse:
    return render(request, "crm/config_index.html", {})


@login_required
def config_pipelines(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            CrmPipeline.objects.create(
                tenant=tenant,
                name=request.POST.get("name", ""),
                is_default=bool(request.POST.get("is_default")),
            )
        except (ValidationError, IntegrityError) as exc:
            error = str(exc)

    pipelines = CrmPipeline.objects.filter(tenant=tenant).order_by("name")
    return render(
        request,
        "crm/config_pipelines.html",
        {"pipelines": pipelines, "error": error},
    )


@login_required
def config_pipeline_detail(request: HttpRequest, pipeline_id: str) -> HttpResponse:
    tenant = resolve_tenant(request)
    pipeline = get_object_or_404(CrmPipeline, id=pipeline_id, tenant=tenant)
    error = None

    if request.method == "POST":
        try:
            CrmStage.objects.create(
                tenant=tenant,
                pipeline=pipeline,
                code=request.POST.get("code", ""),
                name=request.POST.get("name", ""),
                sequence=int(request.POST.get("sequence") or 0),
                probability=int(request.POST.get("probability") or 0),
                is_won=bool(request.POST.get("is_won")),
                is_lost=bool(request.POST.get("is_lost")),
                requires_reason=bool(request.POST.get("requires_reason")),
            )
        except (ValidationError, ValueError, IntegrityError) as exc:
            error = str(exc)

    return render(
        request,
        "crm/config_pipeline_detail.html",
        {"pipeline": pipeline, "stages": pipeline.stages.all(), "error": error},
    )


@login_required
def config_teams(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    users = User.objects.all().order_by("email")
    error = None

    if request.method == "POST":
        try:
            leader_id = request.POST.get("leader_id") or None
            leader = users.get(id=leader_id) if leader_id else None
            CrmTeam.objects.create(
                tenant=tenant,
                name=request.POST.get("name", ""),
                leader=leader,
            )
        except User.DoesNotExist:
            error = _("Responsable introuvable.")
        except (ValidationError, IntegrityError) as exc:
            error = str(exc)

    teams = CrmTeam.objects.filter(tenant=tenant).order_by("name")
    return render(
        request,
        "crm/config_teams.html",
        {"teams": teams, "users": users, "error": error},
    )


@login_required
def config_lost_reasons(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            CrmLostReason.objects.create(
                tenant=tenant,
                name=request.POST.get("name", ""),
            )
        except (ValidationError, IntegrityError) as exc:
            error = str(exc)

    lost_reasons = CrmLostReason.objects.filter(tenant=tenant).order_by("name")
    return render(
        request,
        "crm/config_lost_reasons.html",
        {"lost_reasons": lost_reasons, "error": error},
    )
