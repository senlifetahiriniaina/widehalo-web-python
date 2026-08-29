"""API django-ninja du module `projects` (PJ1) — CRUD minimal
projet/tache, juste assez pour donner un point d'ancrage aux etapes
PJ2-PJ15 (Gantt, sprints, EVM, etc.). RBAC : cf.
`apps.core.services.rbac_policy.ROLE_APP_PERMISSIONS["projects"]`."""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.permissions import require_permission
from apps.core.services.workflow import TransitionPermissionError
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

router = Router(tags=["projects"])


class ProjectIn(Schema):
    name: str
    description: str = ""
    methodology: str = PrjProject.METHODOLOGY_WATERFALL
    client_partner_id: str | None = None
    start_date: str | None = None
    end_date: str | None = None


class TaskIn(Schema):
    task_type: str = PrjTask.TYPE_TASK
    parent_id: str | None = None
    assignee_id: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    duration_days: int = 0
    story_points: int | None = None


def _serialize_project(project: PrjProject) -> dict[str, Any]:
    return {
        "id": str(project.id),
        "reference": project.reference,
        "name": project.name,
        "description": project.description,
        "methodology": project.methodology,
        "status": project.status,
        "start_date": project.start_date.isoformat() if project.start_date else None,
        "end_date": project.end_date.isoformat() if project.end_date else None,
        "client_partner_id": str(project.client_partner_id) if project.client_partner_id else None,
        "linked_objective_id": (
            str(project.linked_objective_id) if project.linked_objective_id else None
        ),
    }


def _serialize_task(task: PrjTask) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "reference": task.reference,
        "project_id": str(task.project_id),
        "task_type": task.task_type,
        "parent_id": str(task.parent_id) if task.parent_id else None,
        "assignee_id": str(task.assignee_id) if task.assignee_id else None,
        "state": task.state,
        "start_date": task.start_date.isoformat() if task.start_date else None,
        "end_date": task.end_date.isoformat() if task.end_date else None,
        "duration_days": task.duration_days,
        "percent_complete": task.percent_complete,
        "is_critical_path": task.is_critical_path,
        "story_points": task.story_points,
    }


# NOTE ordre des decorateurs : `@router.xxx` DOIT rester le decorateur
# EXTERNE et `@require_permission(...)` l'INTERNE (juste au-dessus de
# `def`) — meme piege deja documente dans tous les autres `api.py`.
@router.get("/projects")
@require_permission("projects.view_prjproject")
def list_projects_endpoint(request: Any) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    projects = PrjProject.objects.filter(tenant=tenant, is_active=True)
    return {"results": [_serialize_project(p) for p in projects]}


@router.post("/projects")
@require_permission("projects.add_prjproject")
def create_project_endpoint(request: Any, payload: ProjectIn) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    try:
        project = create_project(
            tenant,
            name=payload.name,
            description=payload.description,
            methodology=payload.methodology,
            client_partner_id=payload.client_partner_id,
            start_date=dt.date.fromisoformat(payload.start_date) if payload.start_date else None,
            end_date=dt.date.fromisoformat(payload.end_date) if payload.end_date else None,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return _serialize_project(project)


@router.get("/projects/{project_id}")
@require_permission("projects.view_prjproject")
def project_detail_endpoint(request: Any, project_id: str) -> dict[str, Any]:
    project = get_object_or_404(PrjProject, id=project_id)
    tasks = project.tasks.filter(is_active=True)
    return {**_serialize_project(project), "tasks": [_serialize_task(t) for t in tasks]}


@router.get("/projects/{project_id}/tasks")
@require_permission("projects.view_prjtask")
def list_tasks_endpoint(request: Any, project_id: str) -> dict[str, Any]:
    project = get_object_or_404(PrjProject, id=project_id)
    tasks = project.tasks.filter(is_active=True)
    return {"results": [_serialize_task(t) for t in tasks]}


@router.post("/projects/{project_id}/tasks")
@require_permission("projects.add_prjtask")
def create_task_endpoint(request: Any, project_id: str, payload: TaskIn) -> dict[str, Any]:
    project = get_object_or_404(PrjProject, id=project_id)
    parent = get_object_or_404(PrjTask, id=payload.parent_id) if payload.parent_id else None
    try:
        task = create_task(
            project.tenant,
            project=project,
            task_type=payload.task_type,
            parent=parent,
            start_date=dt.date.fromisoformat(payload.start_date) if payload.start_date else None,
            end_date=dt.date.fromisoformat(payload.end_date) if payload.end_date else None,
            duration_days=payload.duration_days,
            story_points=payload.story_points,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return _serialize_task(task)


@router.get("/projects/tasks/{task_id}")
@require_permission("projects.view_prjtask")
def task_detail_endpoint(request: Any, task_id: str) -> dict[str, Any]:
    task = get_object_or_404(PrjTask, id=task_id)
    return _serialize_task(task)


_TASK_TRANSITIONS = {
    "start": start_task,
    "block": block_task,
    "unblock": unblock_task,
    "finish": finish_task,
    "cancel": cancel_task,
}


@router.post("/projects/tasks/{task_id}/transition/{action}")
@require_permission("projects.change_prjtask")
def transition_task_endpoint(request: Any, task_id: str, action: str) -> dict[str, Any]:
    task = get_object_or_404(PrjTask, id=task_id)
    transition_fn = _TASK_TRANSITIONS.get(action)
    if transition_fn is None:
        return JsonResponse({"detail": "action inconnue"}, status=400)
    user = request.auth
    assert isinstance(user, User)
    try:
        transition_fn(task, user)
    except TransitionPermissionError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    task.refresh_from_db()
    return _serialize_task(task)
