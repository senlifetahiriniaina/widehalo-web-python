"""API django-ninja du module `automation` (Studio de workflow visuel).
RBAC restreint a `admin`/`direction` (cf. plan, section cadrage — un flux
d'automatisation est un mecanisme puissant, pas une operation courante) —
cf. `apps.core.services.rbac_policy.ROLE_APP_PERMISSIONS["admin"|
"direction"]["automation"]`, meme discipline que `financing`."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from apps.automation.models import AutoFlow, AutoRun, AutoRunStep
from apps.automation.services.compiler import compile_canvas_to_steps
from apps.automation.services.flows import (
    add_action_step,
    add_condition_step,
    create_flow,
    set_flow_active,
)
from apps.core.models.tenant import Tenant
from apps.core.services.automation_registry import list_registered_actions
from apps.core.services.permissions import require_permission

router = Router(tags=["automation"])


class FlowIn(Schema):
    name: str
    trigger_event_type: str
    description: str = ""
    trigger_filter: dict[str, Any] = {}


class ConditionStepIn(Schema):
    expression: str
    next_step_id: str | None = None
    next_step_on_false_id: str | None = None


class ActionStepIn(Schema):
    action_code: str
    param_mapping: dict[str, Any] = {}
    next_step_id: str | None = None


class CanvasIn(Schema):
    canvas_layout: dict[str, Any]


def _serialize_flow(flow: AutoFlow) -> dict[str, Any]:
    return {
        "id": str(flow.id),
        "reference": flow.reference,
        "name": flow.name,
        "description": flow.description,
        "trigger_event_type": flow.trigger_event_type,
        "trigger_filter": flow.trigger_filter,
        "is_active": flow.is_active,
    }


def _serialize_run(run: AutoRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "flow_id": str(run.flow_id),
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "triggering_event_id": str(run.triggering_event_id) if run.triggering_event_id else None,
    }


def _serialize_run_step(step: AutoRunStep) -> dict[str, Any]:
    return {
        "id": str(step.id),
        "step_id": str(step.step_id) if step.step_id else None,
        "status": step.status,
        "result": step.result,
        "error": step.error,
        "retry_count": step.retry_count,
        "executed_at": step.executed_at.isoformat(),
    }


# NOTE ordre des decorateurs : `@router.xxx` DOIT rester le decorateur
# EXTERNE et `@require_permission(...)` l'INTERNE (juste au-dessus de
# `def`) — meme piege deja documente dans tous les autres `api.py`.
@router.get("/automation/actions")
@require_permission("automation.view_autoflow")
def list_actions_endpoint(request: Any) -> dict[str, Any]:
    """Catalogue des actions disponibles pour la palette du constructeur —
    alimente `apps.core.services.automation_registry`."""
    return {
        "results": [
            {
                "code": action.code,
                "module": action.module,
                "label": action.label,
                "param_schema": action.param_schema,
            }
            for action in list_registered_actions()
        ]
    }


@router.get("/automation/flows")
@require_permission("automation.view_autoflow")
def list_flows_endpoint(request: Any) -> dict[str, Any]:
    flows = AutoFlow.objects.filter(is_active__in=[True, False])
    return {"results": [_serialize_flow(f) for f in flows]}


@router.post("/automation/flows")
@require_permission("automation.add_autoflow")
def create_flow_endpoint(request: Any, payload: FlowIn) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    try:
        flow = create_flow(
            tenant,
            name=payload.name,
            trigger_event_type=payload.trigger_event_type,
            description=payload.description,
            trigger_filter=payload.trigger_filter,
            created_by=request.auth,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return _serialize_flow(flow)


@router.get("/automation/flows/{flow_id}")
@require_permission("automation.view_autoflow")
def flow_detail_endpoint(request: Any, flow_id: str) -> dict[str, Any]:
    flow = get_object_or_404(AutoFlow, id=flow_id)
    steps = flow.steps.filter(is_active=True)
    return {
        **_serialize_flow(flow),
        "steps": [
            {
                "id": str(s.id),
                "step_type": s.step_type,
                "config": s.config,
                "next_step_id": str(s.next_step_id) if s.next_step_id else None,
                "next_step_on_false_id": str(s.next_step_on_false_id)
                if s.next_step_on_false_id
                else None,
            }
            for s in steps
        ],
    }


@router.post("/automation/flows/{flow_id}/activate")
@require_permission("automation.change_autoflow")
def activate_flow_endpoint(request: Any, flow_id: str, is_active: bool) -> dict[str, Any]:
    flow = get_object_or_404(AutoFlow, id=flow_id)
    flow = set_flow_active(flow, is_active=is_active)
    return _serialize_flow(flow)


@router.post("/automation/flows/{flow_id}/steps/condition")
@require_permission("automation.change_autoflow")
def add_condition_step_endpoint(
    request: Any, flow_id: str, payload: ConditionStepIn
) -> dict[str, Any]:
    flow = get_object_or_404(AutoFlow, id=flow_id)
    next_step = (
        get_object_or_404(flow.steps, id=payload.next_step_id) if payload.next_step_id else None
    )
    next_step_on_false = (
        get_object_or_404(flow.steps, id=payload.next_step_on_false_id)
        if payload.next_step_on_false_id
        else None
    )
    step = add_condition_step(
        flow,
        expression=payload.expression,
        next_step=next_step,
        next_step_on_false=next_step_on_false,
    )
    return {"id": str(step.id), "step_type": step.step_type, "config": step.config}


@router.post("/automation/flows/{flow_id}/steps/action")
@require_permission("automation.change_autoflow")
def add_action_step_endpoint(request: Any, flow_id: str, payload: ActionStepIn) -> dict[str, Any]:
    flow = get_object_or_404(AutoFlow, id=flow_id)
    next_step = (
        get_object_or_404(flow.steps, id=payload.next_step_id) if payload.next_step_id else None
    )
    try:
        step = add_action_step(
            flow,
            action_code=payload.action_code,
            param_mapping=payload.param_mapping,
            next_step=next_step,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return {"id": str(step.id), "step_type": step.step_type, "config": step.config}


@router.post("/automation/flows/{flow_id}/canvas")
@require_permission("automation.change_autoflow")
def save_canvas_endpoint(request: Any, flow_id: str, payload: CanvasIn) -> dict[str, Any]:
    """Sauvegarde le canevas visuel ET compile le graphe `AutoStep`
    executable a partir de son contenu (cf.
    `apps.automation.services.compiler`)."""
    flow = get_object_or_404(AutoFlow, id=flow_id)
    try:
        compile_canvas_to_steps(flow, payload.canvas_layout)
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return _serialize_flow(flow)


@router.get("/automation/flows/{flow_id}/runs")
@require_permission("automation.view_autoflow")
def list_runs_endpoint(request: Any, flow_id: str) -> dict[str, Any]:
    flow = get_object_or_404(AutoFlow, id=flow_id)
    runs = AutoRun.objects.filter(flow=flow).order_by("-started_at")
    return {"results": [_serialize_run(r) for r in runs]}


@router.get("/automation/runs/{run_id}")
@require_permission("automation.view_autoflow")
def run_detail_endpoint(request: Any, run_id: str) -> dict[str, Any]:
    run = get_object_or_404(AutoRun, id=run_id)
    steps = AutoRunStep.objects.filter(run=run).order_by("executed_at")
    return {**_serialize_run(run), "steps": [_serialize_run_step(s) for s in steps]}
