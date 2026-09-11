"""Ecrans de configuration/master-data du module `crm` (U3), regroupes
sous le hub "Parametres" (cf. decision de placement, plan Lot 2)."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext_lazy as _

from apps.core.models.user import User
from apps.core.services.permissions import screen_forbidden, screen_permission
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant
from apps.crm.models import CrmLostReason, CrmPipeline, CrmStage, CrmTeam

PIPELINE_COLUMNS = [
    Column(key="name", label=_("Nom")),
    Column(key="is_default", label=_("Par défaut"), format="bool", searchable=False),
    Column(key="stagnant_after_days", label=_("Relance (jours)"), searchable=False),
]

TEAM_COLUMNS = [
    Column(key="name", label=_("Nom")),
    Column(key="leader", label=_("Responsable"), search_key="leader__email"),
]

LOST_REASON_COLUMNS = [
    Column(key="name", label=_("Motif")),
]


@login_required
@screen_permission("crm.view_crmpipeline")
def config_index(request: HttpRequest) -> HttpResponse:
    return render(request, "crm/config_index.html", {})


@login_required
@screen_permission("crm.view_crmpipeline")
def config_pipelines(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        refus = screen_forbidden(request, "crm.add_crmpipeline")
        if refus is not None:
            return refus
        try:
            CrmPipeline.objects.create(
                tenant=tenant,
                name=request.POST.get("name", ""),
                is_default=bool(request.POST.get("is_default")),
            )
        except (ValidationError, IntegrityError) as exc:
            error = str(exc)

    return smart_table_response(
        request,
        table_key="crm.pipelines",
        columns=PIPELINE_COLUMNS,
        queryset=CrmPipeline.objects.filter(tenant=tenant),
        page_template="crm/config_pipelines.html",
        # Sans ce lien de ligne, la fiche d'un pipeline n'est plus citee nulle
        # part : la table remplacee par le composant portait le seul chemin
        # vers elle. La garde d'atteignabilite (T10) l'a vu ; la relecture
        # non.
        page_context={"row_url_name": "crm:config_pipeline_detail", "error": error},
    )


@login_required
@screen_permission("crm.view_crmpipeline")
def config_pipeline_detail(request: HttpRequest, pipeline_id: str) -> HttpResponse:
    tenant = resolve_tenant(request)
    pipeline = get_object_or_404(CrmPipeline, id=pipeline_id, tenant=tenant)
    error = None

    if request.method == "POST":
        # Regler le delai de stagnation MODIFIE le pipeline ; l'autre
        # branche CREE une etape. Deux verbes, deux droits.
        refus = screen_forbidden(
            request,
            "crm.change_crmpipeline"
            if request.POST.get("action") == "set_stagnation"
            else "crm.add_crmstage",
        )
        if refus is not None:
            return refus

    if request.method == "POST" and request.POST.get("action") == "set_stagnation":
        # CRM-4 : le « N paramétrable » du critère. Sans cette porte, le
        # champ existerait en base et resterait inatteignable — le motif
        # exact que ce chantier corrige depuis le début.
        try:
            days = int(request.POST.get("stagnant_after_days") or 0)
        except ValueError:
            error = str(_("Le délai de relance doit être un nombre de jours."))
        else:
            if days <= 0:
                error = str(_("Le délai de relance doit être strictement positif."))
            else:
                pipeline.stagnant_after_days = days
                pipeline.save(update_fields=["stagnant_after_days"])
    elif request.method == "POST":
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
@screen_permission("crm.view_crmteam")
def config_teams(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    users = User.objects.all().order_by("email")
    error = None

    if request.method == "POST":
        refus = screen_forbidden(request, "crm.add_crmteam")
        if refus is not None:
            return refus
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

    return smart_table_response(
        request,
        table_key="crm.teams",
        columns=TEAM_COLUMNS,
        queryset=CrmTeam.objects.filter(tenant=tenant),
        page_template="crm/config_teams.html",
        page_context={"users": users, "error": error},
    )


@login_required
@screen_permission("crm.view_crmlostreason")
def config_lost_reasons(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        refus = screen_forbidden(request, "crm.add_crmlostreason")
        if refus is not None:
            return refus
        try:
            CrmLostReason.objects.create(
                tenant=tenant,
                name=request.POST.get("name", ""),
            )
        except (ValidationError, IntegrityError) as exc:
            error = str(exc)

    return smart_table_response(
        request,
        table_key="crm.lost_reasons",
        columns=LOST_REASON_COLUMNS,
        queryset=CrmLostReason.objects.filter(tenant=tenant),
        page_template="crm/config_lost_reasons.html",
        page_context={"error": error},
    )
