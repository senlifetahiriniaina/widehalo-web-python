"""API django-ninja du module `projects` (PJ1) — CRUD minimal
projet/tache, juste assez pour donner un point d'ancrage aux etapes
PJ2-PJ15 (Gantt, sprints, EVM, etc.). RBAC : cf.
`apps.core.services.rbac_policy.ROLE_APP_PERMISSIONS["projects"]`."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from ninja import File, Router, Schema
from ninja.files import UploadedFile

from apps.core.models.document import Document
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.permissions import require_permission
from apps.core.services.workflow import TransitionPermissionError
from apps.projects.models import (
    PrjBudgetLine,
    PrjCustomFieldDefinition,
    PrjInvoicingRecord,
    PrjProject,
    PrjSprint,
    PrjTask,
    PrjTeamMember,
    PrjTimeEntry,
    PrjWikiPage,
)
from apps.projects.services.billing import (
    bill_by_milestone,
    bill_by_percentage,
    bill_fixed,
    bill_time_and_material,
)
from apps.projects.services.capacity import (
    add_team_member,
    compute_project_capacity_summary,
    compute_user_workload_heatmap,
    remove_team_member,
)
from apps.projects.services.evm import add_budget_line, refresh_project_health
from apps.projects.services.gantt import compute_critical_path
from apps.projects.services.projects import create_project
from apps.projects.services.sprints import (
    complete_sprint,
    compute_burndown,
    compute_velocity,
    create_sprint,
    get_backlog,
    start_sprint,
)
from apps.projects.services.tasks import (
    block_task,
    cancel_task,
    create_task,
    finish_task,
    start_task,
    unblock_task,
)
from apps.projects.services.time_tracking import (
    get_time_report,
    log_manual_time_entry,
    start_timer,
    stop_timer,
)
from apps.projects.services.wiki import (
    attach_document_to_project,
    attach_document_to_wiki_page,
    create_wiki_page,
    list_documents_for,
    list_wiki_pages,
    update_wiki_page,
)

router = Router(tags=["projects"])


class ProjectIn(Schema):
    name: str
    description: str = ""
    methodology: str = PrjProject.METHODOLOGY_WATERFALL
    client_partner_id: str | None = None
    start_date: str | None = None
    end_date: str | None = None


class TaskGanttIn(Schema):
    """Payload de l'endpoint PATCH drag-and-drop (PJ2) — tous les champs
    sont optionnels : seuls ceux fournis sont mis a jour."""

    start_date: str | None = None
    end_date: str | None = None
    duration_days: int | None = None


class BudgetLineIn(Schema):
    """Montants toujours en `Decimal` (jamais `float`) — meme discipline
    stricte que le reste de ce projet, cf. `apps/projects/services/evm.py`."""

    category: str = PrjBudgetLine.CATEGORY_OPEX
    label: str
    planned_amount: Decimal
    actual_amount: Decimal = Decimal("0")
    period: str


class BillMilestoneIn(Schema):
    task_id: str


class BillFixedIn(Schema):
    amount: Decimal


class BillTimeAndMaterialIn(Schema):
    hourly_rate: Decimal


class SprintIn(Schema):
    name: str
    start_date: str
    end_date: str
    goal: str = ""


class TeamMemberIn(Schema):
    user_id: str
    role: str = ""
    allocation_pct: int


class CustomFieldDefinitionIn(Schema):
    entity_type: str
    field_key: str
    field_label: str
    field_type: str
    validation_rule: dict[str, Any] = {}


class ManualTimeEntryIn(Schema):
    """Saisie manuelle a posteriori (sans chrono) — cf. `services/time_
    tracking.py::log_manual_time_entry`."""

    started_at: str
    stopped_at: str
    billable: bool = True
    note: str = ""


class WikiPageIn(Schema):
    title: str
    body: str = ""
    parent_id: str | None = None


class WikiPageUpdateIn(Schema):
    """Tous les champs optionnels — seuls ceux fournis sont mis a jour,
    cf. `services/wiki.py::update_wiki_page`."""

    title: str | None = None
    body: str | None = None


class TaskIn(Schema):
    task_type: str = PrjTask.TYPE_TASK
    parent_id: str | None = None
    assignee_id: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    duration_days: int = 0
    story_points: int | None = None
    custom_fields: dict[str, Any] = {}


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


def _serialize_budget_line(line: PrjBudgetLine) -> dict[str, Any]:
    return {
        "id": str(line.id),
        "category": line.category,
        "label": line.label,
        "planned_amount": str(line.planned_amount),
        "actual_amount": str(line.actual_amount),
        "period": line.period.isoformat(),
    }


def _serialize_evm_snapshot(snapshot: Any) -> dict[str, Any]:
    def _dec(value: Decimal | None) -> str | None:
        return str(value) if value is not None else None

    return {
        "pv": _dec(snapshot.pv),
        "ev": _dec(snapshot.ev),
        "ac": _dec(snapshot.ac),
        "bac": _dec(snapshot.bac),
        "spi": _dec(snapshot.spi),
        "cpi": _dec(snapshot.cpi),
        "eac": _dec(snapshot.eac),
    }


def _serialize_sprint(sprint: PrjSprint) -> dict[str, Any]:
    return {
        "id": str(sprint.id),
        "project_id": str(sprint.project_id),
        "name": sprint.name,
        "start_date": sprint.start_date.isoformat(),
        "end_date": sprint.end_date.isoformat(),
        "status": sprint.status,
        "goal": sprint.goal,
    }


def _serialize_time_entry(entry: PrjTimeEntry) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "task_id": str(entry.task_id),
        "user_id": str(entry.user_id),
        "started_at": entry.started_at.isoformat(),
        "stopped_at": entry.stopped_at.isoformat() if entry.stopped_at else None,
        "duration_minutes": entry.duration_minutes,
        "billable": entry.billable,
        "billed": entry.billed,
        "note": entry.note,
    }


def _serialize_wiki_page(page: PrjWikiPage) -> dict[str, Any]:
    return {
        "id": str(page.id),
        "project_id": str(page.project_id),
        "parent_id": str(page.parent_id) if page.parent_id else None,
        "title": page.title,
        "body": page.body,
        "author_id": str(page.author_id) if page.author_id else None,
    }


def _serialize_document(document: Document) -> dict[str, Any]:
    return {
        "id": str(document.id),
        "original_name": document.original_name,
        "mime_type": document.mime_type,
        "size": document.size,
        "sha256": document.sha256,
        "av_scan_status": document.av_scan_status,
    }


def _serialize_task(task: PrjTask) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "reference": task.reference,
        "project_id": str(task.project_id),
        "task_type": task.task_type,
        "parent_id": str(task.parent_id) if task.parent_id else None,
        "sprint_id": str(task.sprint_id) if task.sprint_id else None,
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
            custom_fields=payload.custom_fields,
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


@router.patch("/projects/tasks/{task_id}/gantt")
@require_permission("projects.change_prjtask")
def update_task_gantt_endpoint(request: Any, task_id: str, payload: TaskGanttIn) -> dict[str, Any]:
    """Endpoint drag-and-drop (PJ2) : met a jour `start_date`/`end_date`/
    `duration_days` d'une tache puis recalcule automatiquement le chemin
    critique (CPM) de tout le projet — cf. `services/gantt.py::
    compute_critical_path`. RBAC identique aux autres endpoints de gestion
    de projet (`projects.change_prjtask`, accorde a `resp_commercial`/
    `resp_production`/`admin`/`direction`, cf. `rbac_policy.py`)."""
    task = get_object_or_404(PrjTask, id=task_id)
    update_fields = []
    if payload.start_date is not None:
        task.start_date = dt.date.fromisoformat(payload.start_date)
        update_fields.append("start_date")
    if payload.end_date is not None:
        task.end_date = dt.date.fromisoformat(payload.end_date)
        update_fields.append("end_date")
    if payload.duration_days is not None:
        task.duration_days = payload.duration_days
        update_fields.append("duration_days")
    if update_fields:
        task.save(update_fields=update_fields)
    compute_critical_path(task.project)
    task.refresh_from_db()
    return _serialize_task(task)


@router.get("/projects/{project_id}/budget")
@require_permission("projects.view_prjproject")
def project_budget_endpoint(request: Any, project_id: str) -> dict[str, Any]:
    """PJ4 : lignes budgetaires du projet + instantane EVM (SPI/CPI/EAC)
    calcule a la date du jour — cf. `services/evm.py::compute_evm_
    snapshot`. Met egalement a jour `PrjProject.status` selon la politique
    de seuils (`refresh_project_health`), coherent avec la lecture du
    detail projet qui affiche ce statut."""
    project = get_object_or_404(PrjProject, id=project_id)
    snapshot = refresh_project_health(project)
    lines = project.budget_lines.filter(is_active=True)
    return {
        "project_id": str(project.id),
        "status": project.status,
        "lines": [_serialize_budget_line(line) for line in lines],
        "evm": _serialize_evm_snapshot(snapshot),
    }


@router.post("/projects/{project_id}/budget")
@require_permission("projects.add_prjbudgetline")
def create_budget_line_endpoint(
    request: Any, project_id: str, payload: BudgetLineIn
) -> dict[str, Any]:
    project = get_object_or_404(PrjProject, id=project_id)
    try:
        line = add_budget_line(
            project,
            category=payload.category,
            label=payload.label,
            planned_amount=payload.planned_amount,
            actual_amount=payload.actual_amount,
            period=dt.date.fromisoformat(payload.period),
        )
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return _serialize_budget_line(line)


def _serialize_invoicing_record(record: PrjInvoicingRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "project_id": str(record.project_id),
        "task_id": str(record.task_id) if record.task_id else None,
        "mode": record.mode,
        "amount": str(record.amount),
        "invoice_id": str(record.invoice_id),
        "billed_date": record.billed_date.isoformat(),
    }


# NOTE RBAC : `projects.bill_prjproject` (permission PERSONNALISEE, cf.
# `PrjProject.Meta.permissions`) plutot que le simple `projects.change_
# prjproject` (deja accorde a resp_commercial/resp_production/admin/
# direction) — la facturation est une operation plus sensible que le CRUD
# projet/tache courant (genere une ecriture comptable engageant le tenant
# vis-a-vis d'un client), meme discipline que `accounting.validate_accmove`
# (cf. `apps.core.services.rbac_policy.CUSTOM_PERMISSIONS`). Restreinte a
# admin/direction/resp_commercial (cf. ce meme registre) — PAS
# resp_production, qui gere la production/les taches mais n'engage pas la
# facturation client.
@router.post("/projects/{project_id}/bill/milestone")
@require_permission("projects.bill_prjproject")
def bill_milestone_endpoint(
    request: Any, project_id: str, payload: BillMilestoneIn
) -> dict[str, Any]:
    project = get_object_or_404(PrjProject, id=project_id)
    task = get_object_or_404(PrjTask, id=payload.task_id, project=project)
    user = request.auth
    assert isinstance(user, User)
    try:
        bill_by_milestone(project, task, user)
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    record = project.invoicing_records.filter(
        task=task, mode=PrjInvoicingRecord.MODE_MILESTONE
    ).latest("created_at")
    return _serialize_invoicing_record(record)


@router.post("/projects/{project_id}/bill/percentage")
@require_permission("projects.bill_prjproject")
def bill_percentage_endpoint(request: Any, project_id: str) -> dict[str, Any]:
    project = get_object_or_404(PrjProject, id=project_id)
    user = request.auth
    assert isinstance(user, User)
    try:
        bill_by_percentage(project, user)
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    record = project.invoicing_records.filter(mode=PrjInvoicingRecord.MODE_PERCENTAGE).latest(
        "created_at"
    )
    return _serialize_invoicing_record(record)


@router.post("/projects/{project_id}/bill/fixed")
@require_permission("projects.bill_prjproject")
def bill_fixed_endpoint(request: Any, project_id: str, payload: BillFixedIn) -> dict[str, Any]:
    project = get_object_or_404(PrjProject, id=project_id)
    user = request.auth
    assert isinstance(user, User)
    try:
        bill_fixed(project, user, amount=payload.amount)
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    record = project.invoicing_records.filter(mode=PrjInvoicingRecord.MODE_FIXED).latest(
        "created_at"
    )
    return _serialize_invoicing_record(record)


@router.post("/projects/{project_id}/bill/time-and-material")
@require_permission("projects.bill_prjproject")
def bill_time_and_material_endpoint(
    request: Any, project_id: str, payload: BillTimeAndMaterialIn
) -> dict[str, Any]:
    """Cf. `services/billing.py::bill_time_and_material` — desormais
    implemente (PJ8, `PrjTimeEntry`) : jamais plus de 501, meme patron 200/
    400 que les 3 autres modes."""
    project = get_object_or_404(PrjProject, id=project_id)
    user = request.auth
    assert isinstance(user, User)
    try:
        bill_time_and_material(project, user, hourly_rate=payload.hourly_rate)
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    record = project.invoicing_records.filter(
        mode=PrjInvoicingRecord.MODE_TIME_AND_MATERIAL
    ).latest("created_at")
    return _serialize_invoicing_record(record)


# ---------------------------------------------------------------------------
# PJ6 — Sprints agiles (backlog/burndown/velocite). RBAC : memes permissions
# app-level "projects" (view/add/change) que le CRUD projet/tache courant
# (cf. `ROLE_APP_PERMISSIONS`) — la creation/demarrage/cloture d'un sprint
# n'est PAS une operation aussi sensible que la facturation (PJ5), pas de
# permission personnalisee dediee necessaire.
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/sprints")
@require_permission("projects.view_prjsprint")
def list_sprints_endpoint(request: Any, project_id: str) -> dict[str, Any]:
    project = get_object_or_404(PrjProject, id=project_id)
    sprints = project.sprints.filter(is_active=True)
    return {"results": [_serialize_sprint(s) for s in sprints]}


@router.post("/projects/{project_id}/sprints")
@require_permission("projects.add_prjsprint")
def create_sprint_endpoint(request: Any, project_id: str, payload: SprintIn) -> dict[str, Any]:
    project = get_object_or_404(PrjProject, id=project_id)
    try:
        sprint = create_sprint(
            project,
            name=payload.name,
            start_date=dt.date.fromisoformat(payload.start_date),
            end_date=dt.date.fromisoformat(payload.end_date),
            goal=payload.goal,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return _serialize_sprint(sprint)


@router.post("/projects/{project_id}/sprints/{sprint_id}/start")
@require_permission("projects.change_prjsprint")
def start_sprint_endpoint(request: Any, project_id: str, sprint_id: str) -> dict[str, Any]:
    sprint = get_object_or_404(PrjSprint, id=sprint_id, project_id=project_id)
    try:
        start_sprint(sprint)
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return _serialize_sprint(sprint)


@router.post("/projects/{project_id}/sprints/{sprint_id}/complete")
@require_permission("projects.change_prjsprint")
def complete_sprint_endpoint(request: Any, project_id: str, sprint_id: str) -> dict[str, Any]:
    sprint = get_object_or_404(PrjSprint, id=sprint_id, project_id=project_id)
    complete_sprint(sprint)
    return _serialize_sprint(sprint)


@router.get("/projects/{project_id}/backlog")
@require_permission("projects.view_prjtask")
def project_backlog_endpoint(request: Any, project_id: str) -> dict[str, Any]:
    project = get_object_or_404(PrjProject, id=project_id)
    return {"results": [_serialize_task(t) for t in get_backlog(project)]}


@router.get("/projects/{project_id}/sprints/{sprint_id}/burndown")
@require_permission("projects.view_prjsprint")
def sprint_burndown_endpoint(request: Any, project_id: str, sprint_id: str) -> dict[str, Any]:
    sprint = get_object_or_404(PrjSprint, id=sprint_id, project_id=project_id)
    burndown = compute_burndown(sprint)
    return {
        "sprint_id": str(sprint.id),
        "burndown": [
            {
                "date": point["date"].isoformat(),
                "story_points_remaining": str(point["story_points_remaining"]),
            }
            for point in burndown
        ],
    }


@router.get("/projects/{project_id}/velocity")
@require_permission("projects.view_prjsprint")
def project_velocity_endpoint(request: Any, project_id: str) -> dict[str, Any]:
    project = get_object_or_404(PrjProject, id=project_id)
    return {"project_id": str(project.id), "velocity": str(compute_velocity(project))}


# ---------------------------------------------------------------------------
# PJ7 — Equipe projet + heatmap de capacite. RBAC : memes permissions
# app-level "projects" (view/add/change) que le CRUD projet/tache/sprint
# courant (cf. `ROLE_APP_PERMISSIONS`) — gerer l'equipe d'un projet n'est
# PAS aussi sensible que la facturation (PJ5), pas de permission
# personnalisee dediee.
# ---------------------------------------------------------------------------


def _serialize_team_member(member: PrjTeamMember) -> dict[str, Any]:
    return {
        "id": str(member.id),
        "project_id": str(member.project_id),
        "user_id": str(member.user_id),
        "role": member.role,
        "allocation_pct": member.allocation_pct,
    }


@router.get("/projects/{project_id}/team")
@require_permission("projects.view_prjteammember")
def project_team_endpoint(request: Any, project_id: str) -> dict[str, Any]:
    project = get_object_or_404(PrjProject, id=project_id)
    return compute_project_capacity_summary(project)


@router.post("/projects/{project_id}/team")
@require_permission("projects.add_prjteammember")
def add_team_member_endpoint(
    request: Any, project_id: str, payload: TeamMemberIn
) -> dict[str, Any]:
    project = get_object_or_404(PrjProject, id=project_id)
    user = get_object_or_404(User, id=payload.user_id)
    try:
        member = add_team_member(
            project, user, role=payload.role, allocation_pct=payload.allocation_pct
        )
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return _serialize_team_member(member)


@router.post("/projects/{project_id}/team/{member_id}/remove")
@require_permission("projects.change_prjteammember")
def remove_team_member_endpoint(request: Any, project_id: str, member_id: str) -> dict[str, Any]:
    member = get_object_or_404(PrjTeamMember, id=member_id, project_id=project_id)
    remove_team_member(member)
    return {"id": str(member.id), "is_active": member.is_active}


@router.get("/projects/users/{user_id}/capacity-heatmap")
@require_permission("projects.view_prjteammember")
def user_capacity_heatmap_endpoint(request: Any, user_id: str) -> dict[str, Any]:
    user = get_object_or_404(User, id=user_id)
    heatmap = compute_user_workload_heatmap(user)
    return {
        "user_id": str(user.id),
        "weeks": [
            {
                "week_start": week["week_start"].isoformat(),
                "week_end": week["week_end"].isoformat(),
                "allocation_pct": week["allocation_pct"],
                "active_task_count": week["active_task_count"],
                "is_overallocated": week["is_overallocated"],
            }
            for week in heatmap
        ],
    }


# ---------------------------------------------------------------------------
# PJ7 — Champs personnalises. RBAC : `projects.manage_prjcustomfielddefinition`
# (permission PERSONNALISEE, cf. `PrjCustomFieldDefinition.Meta.permissions`)
# restreinte a `admin`/`direction` — un PARAMETRAGE, pas une operation
# courante de gestion de projet (meme discipline que
# `projects.bill_prjproject`, cf. `apps.core.services.rbac_policy`).
# ---------------------------------------------------------------------------


def _serialize_custom_field_definition(definition: PrjCustomFieldDefinition) -> dict[str, Any]:
    return {
        "id": str(definition.id),
        "entity_type": definition.entity_type,
        "field_key": definition.field_key,
        "field_label": definition.field_label,
        "field_type": definition.field_type,
        "validation_rule": definition.validation_rule,
    }


@router.get("/projects/config/custom-fields")
@require_permission("projects.manage_prjcustomfielddefinition")
def list_custom_field_definitions_endpoint(request: Any) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    definitions = PrjCustomFieldDefinition.objects.filter(tenant=tenant, is_active=True)
    return {"results": [_serialize_custom_field_definition(d) for d in definitions]}


@router.post("/projects/config/custom-fields")
@require_permission("projects.manage_prjcustomfielddefinition")
def create_custom_field_definition_endpoint(
    request: Any, payload: CustomFieldDefinitionIn
) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    try:
        definition = PrjCustomFieldDefinition.objects.create(
            tenant=tenant,
            entity_type=payload.entity_type,
            field_key=payload.field_key,
            field_label=payload.field_label,
            field_type=payload.field_type,
            validation_rule=payload.validation_rule,
        )
    except (ValidationError, IntegrityError) as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return _serialize_custom_field_definition(definition)


@router.post("/projects/config/custom-fields/{definition_id}/remove")
@require_permission("projects.manage_prjcustomfielddefinition")
def remove_custom_field_definition_endpoint(request: Any, definition_id: str) -> dict[str, Any]:
    definition = get_object_or_404(PrjCustomFieldDefinition, id=definition_id)
    definition.soft_delete()
    return {"id": str(definition.id), "is_active": definition.is_active}


# ---------------------------------------------------------------------------
# PJ8 — Suivi du temps. RBAC : permission PERSONNALISEE `projects.track_
# prjtimeentry` (declaree en `Meta.permissions` de `PrjTimeEntry`) plutot
# que les codenames auto-generes `add/change_prjtimeentry` de
# `ROLE_APP_PERMISSIONS["projects"]` — ce dernier n'accorde PAS "add" a
# `collaborateur` (cf. sa docstring de role : "gere ses taches assignees et
# son propre suivi du temps"), or un `collaborateur` DOIT pouvoir demarrer
# son propre chrono. Cette permission personnalisee est donc accordee a
# TOUS les roles ayant acces au module `projects` (admin/direction/
# resp_commercial/resp_production/collaborateur), cf.
# `apps.core.services.rbac_policy.CUSTOM_PERMISSIONS`. **Scope N3** : la
# permission N2 ci-dessus donne seulement le DROIT d'utiliser ces
# endpoints — la restriction reelle "un utilisateur ne gere que SES
# PROPRES entrees" est portee par `services/time_tracking.py` lui-meme
# (`start_timer`/`stop_timer` operent explicitement sur `user=request.
# auth`, `stop_timer` refuse explicitement le chrono d'un tiers), jamais
# par un filtre applique ici en plus.
# ---------------------------------------------------------------------------


@router.post("/projects/tasks/{task_id}/time/start")
@require_permission("projects.track_prjtimeentry")
def start_timer_endpoint(request: Any, task_id: str) -> dict[str, Any]:
    task = get_object_or_404(PrjTask, id=task_id)
    user = request.auth
    assert isinstance(user, User)
    try:
        entry = start_timer(task, user)
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return _serialize_time_entry(entry)


@router.post("/projects/time-entries/{time_entry_id}/stop")
@require_permission("projects.track_prjtimeentry")
def stop_timer_endpoint(request: Any, time_entry_id: str) -> dict[str, Any]:
    time_entry = get_object_or_404(PrjTimeEntry, id=time_entry_id)
    user = request.auth
    assert isinstance(user, User)
    try:
        stop_timer(time_entry, user)
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return _serialize_time_entry(time_entry)


@router.post("/projects/tasks/{task_id}/time/manual")
@require_permission("projects.track_prjtimeentry")
def log_manual_time_entry_endpoint(
    request: Any, task_id: str, payload: ManualTimeEntryIn
) -> dict[str, Any]:
    task = get_object_or_404(PrjTask, id=task_id)
    user = request.auth
    assert isinstance(user, User)
    try:
        entry = log_manual_time_entry(
            task,
            user,
            started_at=dt.datetime.fromisoformat(payload.started_at),
            stopped_at=dt.datetime.fromisoformat(payload.stopped_at),
            billable=payload.billable,
            note=payload.note,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return _serialize_time_entry(entry)


@router.get("/projects/{project_id}/time-report")
@require_permission("projects.track_prjtimeentry")
def project_time_report_endpoint(
    request: Any, project_id: str, date_from: str | None = None, date_to: str | None = None
) -> dict[str, Any]:
    project = get_object_or_404(PrjProject, id=project_id)
    report = get_time_report(
        project,
        date_from=dt.date.fromisoformat(date_from) if date_from else None,
        date_to=dt.date.fromisoformat(date_to) if date_to else None,
    )
    return {
        "project_id": str(project.id),
        "results": [
            {
                "user_id": str(row["user_id"]),
                "total_minutes": row["total_minutes"],
                "billable_minutes": row["billable_minutes"],
                "billed_minutes": row["billed_minutes"],
            }
            for row in report
        ],
    }


# ---------------------------------------------------------------------------
# Wiki projet + rattachement de documents (PJ10) — cf. `services/wiki.py`.
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/wiki")
@require_permission("projects.view_prjwikipage")
def list_wiki_pages_endpoint(request: Any, project_id: str) -> dict[str, Any]:
    project = get_object_or_404(PrjProject, id=project_id)
    pages = list_wiki_pages(project)
    return {"results": [_serialize_wiki_page(page) for page in pages]}


@router.post("/projects/{project_id}/wiki")
@require_permission("projects.add_prjwikipage")
def create_wiki_page_endpoint(request: Any, project_id: str, payload: WikiPageIn) -> dict[str, Any]:
    project = get_object_or_404(PrjProject, id=project_id)
    parent = get_object_or_404(PrjWikiPage, id=payload.parent_id) if payload.parent_id else None
    user = request.auth
    assert isinstance(user, User)
    try:
        page = create_wiki_page(
            project, title=payload.title, body=payload.body, author=user, parent=parent
        )
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return _serialize_wiki_page(page)


@router.get("/projects/wiki/{page_id}")
@require_permission("projects.view_prjwikipage")
def wiki_page_detail_endpoint(request: Any, page_id: str) -> dict[str, Any]:
    page = get_object_or_404(PrjWikiPage, id=page_id)
    return _serialize_wiki_page(page)


@router.patch("/projects/wiki/{page_id}")
@require_permission("projects.change_prjwikipage")
def update_wiki_page_endpoint(
    request: Any, page_id: str, payload: WikiPageUpdateIn
) -> dict[str, Any]:
    page = get_object_or_404(PrjWikiPage, id=page_id)
    page = update_wiki_page(page, title=payload.title, body=payload.body)
    return _serialize_wiki_page(page)


@router.post("/projects/wiki/{page_id}/documents")
@require_permission("projects.change_prjwikipage")
def attach_document_to_wiki_page_endpoint(
    request: Any,
    page_id: str,
    file: UploadedFile = File(...),  # noqa: B008 — idiome django-ninja standard
) -> dict[str, Any]:
    page = get_object_or_404(PrjWikiPage, id=page_id)
    user = request.auth
    assert isinstance(user, User)
    document = attach_document_to_wiki_page(page, file, user)
    return _serialize_document(document)


@router.post("/projects/{project_id}/documents")
@require_permission("projects.change_prjproject")
def attach_document_to_project_endpoint(
    request: Any,
    project_id: str,
    file: UploadedFile = File(...),  # noqa: B008 — idiome django-ninja standard
) -> dict[str, Any]:
    project = get_object_or_404(PrjProject, id=project_id)
    user = request.auth
    assert isinstance(user, User)
    document = attach_document_to_project(project, file, user)
    return _serialize_document(document)


@router.get("/projects/{project_id}/documents")
@require_permission("projects.view_prjproject")
def list_project_documents_endpoint(request: Any, project_id: str) -> dict[str, Any]:
    project = get_object_or_404(PrjProject, id=project_id)
    documents = list_documents_for(project)
    return {"results": [_serialize_document(doc) for doc in documents]}
