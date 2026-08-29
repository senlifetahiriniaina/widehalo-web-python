"""AUTO5/AUTO6 (chantier Studio de workflow visuel) — ecrans HTMX minimaux
du module `automation` : liste des flux, constructeur visuel (canevas
Drawflow + palette), historique d'execution en lecture. Meme patron que
`apps.strategy.views`/`apps.financing.views` : chaque vue appelle
directement les fonctions de service, jamais l'API ninja.

**RBAC** : comme `apps.financing.views`, aucune verification de permission
explicite ici (la RBAC N2 de ce projet est appliquee au niveau API django-
ninja via `require_permission`, jamais au niveau des vues HTML — meme
simplification deja assumee par tous les modules restreints par role,
ex. `financing`) — `@login_required` seul, coherent avec le reste du
projet."""

from __future__ import annotations

import json
from typing import cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.automation.models import AutoFlow, AutoRun, AutoRunStep
from apps.automation.services.compiler import compile_canvas_to_steps
from apps.automation.services.flows import create_flow, set_flow_active
from apps.core.events import PUBLISHED_EVENT_TYPES
from apps.core.models.user import User
from apps.core.services.automation_registry import list_registered_actions
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant

FLOW_COLUMNS = [
    Column(key="reference", label="Reference"),
    Column(key="name", label="Nom"),
    Column(key="trigger_event_type", label="Declencheur", searchable=False),
    Column(key="is_active", label="Actif", searchable=False),
]

RUN_COLUMNS = [
    Column(key="id", label="Identifiant", searchable=False),
    Column(key="status", label="Statut", searchable=False),
    Column(key="started_at", label="Demarre le", searchable=False),
]


@login_required
def flow_list(request: HttpRequest) -> HttpResponse:
    queryset = AutoFlow.objects.filter(is_active__in=[True, False])
    return smart_table_response(
        request,
        table_key="automation.flows",
        columns=FLOW_COLUMNS,
        queryset=queryset,
        page_template="automation/list.html",
        page_context={"row_url_name": "automation:builder"},
    )


@login_required
def flow_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    user = cast(User, request.user)
    error = None
    if request.method == "POST":
        try:
            flow = create_flow(
                tenant,
                name=request.POST.get("name", ""),
                trigger_event_type=request.POST.get("trigger_event_type", ""),
                description=request.POST.get("description", ""),
                created_by=user,
            )
        except ValidationError as exc:
            error = str(exc)
        else:
            return redirect("automation:builder", flow_id=flow.id)
    return render(
        request,
        "automation/create.html",
        {"error": error, "event_types": sorted(PUBLISHED_EVENT_TYPES)},
    )


@login_required
def flow_builder(request: HttpRequest, flow_id: str) -> HttpResponse:
    """Ecran constructeur : canevas Drawflow (vendorise, `static/vendor/
    drawflow/`) + palette de noeuds (condition/action, actions listees
    depuis `core.services.automation_registry`). A la sauvegarde, le
    layout visuel est ET persiste brut ET compile vers le graphe `AutoStep`
    executable (`apps.automation.services.compiler`)."""
    flow = get_object_or_404(AutoFlow, id=flow_id)
    error = None
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "toggle_active":
            set_flow_active(flow, is_active=not flow.is_active)
            return redirect("automation:builder", flow_id=flow.id)
        try:
            canvas_layout = json.loads(request.POST.get("canvas_json", "{}"))
            compile_canvas_to_steps(flow, canvas_layout)
        except (ValidationError, json.JSONDecodeError) as exc:
            error = str(exc)
        else:
            return redirect("automation:builder", flow_id=flow.id)
    return render(
        request,
        "automation/builder.html",
        {
            "flow": flow,
            "error": error,
            "actions": list_registered_actions(),
        },
    )


@login_required
def run_history(request: HttpRequest, flow_id: str) -> HttpResponse:
    flow = get_object_or_404(AutoFlow, id=flow_id)
    queryset = AutoRun.objects.filter(flow=flow).order_by("-started_at")
    return smart_table_response(
        request,
        table_key="automation.runs",
        columns=RUN_COLUMNS,
        queryset=queryset,
        page_template="automation/run_history.html",
        page_context={"row_url_name": "automation:run_detail", "flow": flow},
    )


@login_required
def run_detail(request: HttpRequest, run_id: str) -> HttpResponse:
    run = get_object_or_404(AutoRun, id=run_id)
    steps = AutoRunStep.objects.filter(run=run).order_by("executed_at")
    return render(request, "automation/run_detail.html", {"run": run, "steps": steps})
