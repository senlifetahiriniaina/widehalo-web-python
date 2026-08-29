"""Ecrans HTMX minimaux du module `projects` (PJ1) : liste/creation/detail
de projet, ajout de tache et transitions FSM depuis le detail. Meme patron
que `apps.financing.views`/`apps.feasibility.views` : chaque vue appelle
directement les fonctions de service, jamais l'API ninja. Les vues
riches (Gantt SVG, Kanban, EVM...) arrivent aux etapes PJ2+."""

from __future__ import annotations

from decimal import InvalidOperation
from typing import cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.models.user import User
from apps.core.services.workflow import TransitionPermissionError
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant
from apps.projects.models import PrjProject, PrjTask
from apps.projects.services.projects import create_project
from apps.projects.services.tasks import (
    block_task,
    cancel_task,
    create_task,
    finish_task,
    start_task,
    unblock_task,
)

COLUMNS = [
    Column(key="reference", label="Reference"),
    Column(key="name", label="Nom"),
    Column(key="methodology", label="Methodologie", searchable=False),
    Column(key="status", label="Statut", searchable=False),
]

_TASK_TRANSITIONS = {
    "start": start_task,
    "block": block_task,
    "unblock": unblock_task,
    "finish": finish_task,
    "cancel": cancel_task,
}


@login_required
def project_list(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    queryset = PrjProject.objects.filter(tenant=tenant, is_active=True)
    return smart_table_response(
        request,
        table_key="projects.projects",
        columns=COLUMNS,
        queryset=queryset,
        page_template="projects/list.html",
        page_context={"row_url_name": "projects:detail"},
    )


@login_required
def project_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None
    if request.method == "POST":
        try:
            project = create_project(
                tenant,
                name=request.POST.get("name", ""),
                description=request.POST.get("description", ""),
                methodology=request.POST.get("methodology", PrjProject.METHODOLOGY_WATERFALL),
                owner=cast(User, request.user),
            )
            return redirect("projects:detail", project_id=project.id)
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = str(exc)
    return render(
        request,
        "projects/create.html",
        {"error": error, "methodologies": PrjProject.METHODOLOGY_CHOICES},
    )


@login_required
def project_detail(request: HttpRequest, project_id: str) -> HttpResponse:
    project = get_object_or_404(PrjProject, id=project_id)
    error = None

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "add_task":
                parent_id = request.POST.get("parent_id") or None
                parent = (
                    get_object_or_404(PrjTask, id=parent_id, project=project) if parent_id else None
                )
                create_task(
                    project.tenant,
                    project=project,
                    task_type=request.POST.get("task_type", PrjTask.TYPE_TASK),
                    parent=parent,
                )
            else:
                task_id = request.POST.get("task_id", "")
                task = get_object_or_404(PrjTask, id=task_id, project=project)
                transition_fn = _TASK_TRANSITIONS.get(action or "")
                if transition_fn is not None:
                    transition_fn(task, cast(User, request.user))
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = str(exc)
        except TransitionPermissionError as exc:
            error = str(exc)

    tasks = project.tasks.filter(is_active=True)
    return render(
        request,
        "projects/detail.html",
        {
            "project": project,
            "tasks": tasks,
            "task_types": PrjTask.TYPE_CHOICES,
            "error": error,
        },
    )
