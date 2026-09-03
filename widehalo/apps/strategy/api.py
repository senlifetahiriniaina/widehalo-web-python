"""API django-ninja du module `strategy` (Strategie & Pilotage). Cascade OKR
(objectifs/key results/check-ins), referentiel de benchmarks sectoriels,
notes qualitatives — la generation du business plan reste gerée par le
catalogue `reporting` (`POST /reporting/generate` avec `code=STRATEGY-BP`),
pas un endpoint dedie ici (coherent avec ACC-FAC/PAY-BULL, jamais un second
mecanisme de generation de rapport)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from apps.core.models.tenant import Tenant
from apps.core.services.permissions import require_permission
from apps.strategy.models import StgBudget, StgKeyResult, StgObjective, StgRisk, StgSectorBenchmark
from apps.strategy.services.benchmarks import create_note, get_benchmarks_for_sector
from apps.strategy.services.budget import compute_variance, lock_budget, serialize_variance_row
from apps.strategy.services.objectives import (
    activate_objective,
    add_key_result,
    create_objective,
    record_check_in,
    refresh_key_result_from_source,
)
from apps.strategy.services.risks import create_risk
from apps.strategy.services.scoping import assert_can_manage_level, scope_objectives_for_user

router = Router(tags=["strategy"])


class ObjectiveIn(Schema):
    title: str
    level: str
    description: str = ""
    parent_id: str | None = None
    owner_id: str | None = None
    department_id: str | None = None
    sector_code: str | None = None
    period_start: str
    period_end: str


class KeyResultIn(Schema):
    metric_name: str
    target_value: Decimal
    unit: str = ""
    metric_code: str = ""
    kpi_source_module: str = ""
    kpi_source_function: str = ""


class CheckInIn(Schema):
    date: str
    value: Decimal
    comment: str = ""


class NoteIn(Schema):
    title: str
    body: str = ""
    objective_id: str | None = None


def _serialize_objective(objective: StgObjective) -> dict[str, Any]:
    return {
        "id": str(objective.id),
        "reference": objective.reference,
        "title": objective.title,
        "level": objective.level,
        "status": objective.status,
        "parent_id": str(objective.parent_id) if objective.parent_id else None,
        "department_id": str(objective.department_id) if objective.department_id else None,
        "sector_code": objective.sector_code,
        "period_start": objective.period_start.isoformat(),
        "period_end": objective.period_end.isoformat(),
    }


def _serialize_key_result(key_result: StgKeyResult) -> dict[str, Any]:
    return {
        "id": str(key_result.id),
        "metric_name": key_result.metric_name,
        "target_value": str(key_result.target_value),
        "current_value": str(key_result.current_value),
        "unit": key_result.unit,
        "progress_pct": str(key_result.progress_pct()),
    }


def _serialize_benchmark(benchmark: StgSectorBenchmark) -> dict[str, Any]:
    return {
        "id": str(benchmark.id),
        "sector_code": benchmark.sector_code,
        "kpi_code": benchmark.kpi_code,
        "kpi_label": benchmark.kpi_label,
        "target_min": str(benchmark.target_min) if benchmark.target_min is not None else None,
        "target_max": str(benchmark.target_max) if benchmark.target_max is not None else None,
        "unit": benchmark.unit,
    }


# NOTE ordre des decorateurs : `@router.xxx` DOIT rester le decorateur
# EXTERNE et `@require_permission(...)` l'INTERNE (juste au-dessus de
# `def`) — meme piege deja documente dans tous les autres `api.py`.
@router.get("/strategy/objectives")
@require_permission("strategy.view_stgobjective")
def list_objectives_endpoint(request: Any) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    objectives = scope_objectives_for_user(
        StgObjective.objects.filter(is_active=True), request.auth, tenant
    )
    return {"results": [_serialize_objective(o) for o in objectives]}


@router.post("/strategy/objectives")
@require_permission("strategy.add_stgobjective")
def create_objective_endpoint(request: Any, payload: ObjectiveIn) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    department_id = uuid.UUID(payload.department_id) if payload.department_id else None
    try:
        assert_can_manage_level(
            request.auth, level=payload.level, department_id=department_id, tenant=tenant
        )
    except PermissionDenied as exc:
        return JsonResponse({"detail": str(exc)}, status=403)

    parent = get_object_or_404(StgObjective, id=payload.parent_id) if payload.parent_id else None
    owner = None
    if payload.owner_id:
        from apps.core.models.user import User

        owner = get_object_or_404(User, id=payload.owner_id)

    try:
        objective = create_objective(
            tenant,
            title=payload.title,
            description=payload.description,
            level=payload.level,
            owner=owner,
            parent=parent,
            department_id=department_id,
            sector_code=payload.sector_code,
            period_start=payload.period_start,
            period_end=payload.period_end,
            created_by=request.auth,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return _serialize_objective(objective)


@router.get("/strategy/objectives/{objective_id}")
@require_permission("strategy.view_stgobjective")
def objective_detail_endpoint(request: Any, objective_id: str) -> dict[str, Any]:
    objective = get_object_or_404(StgObjective, id=objective_id)
    key_results = objective.key_results.filter(is_active=True)
    return {
        **_serialize_objective(objective),
        "key_results": [_serialize_key_result(kr) for kr in key_results],
    }


def _get_objective_in_scope(request: Any, objective_id: str) -> StgObjective:
    """N3 : une mutation (ajout de key result/check-in) n'est autorisee que
    sur un objectif DEJA visible par `request.auth` via `scope_objectives_
    for_user` — sinon 404 (jamais un 403 qui confirmerait l'existence d'un
    objectif d'un tiers, meme discipline "pas de faux positif/fuite" que le
    reste du projet)."""
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    queryset = scope_objectives_for_user(
        StgObjective.objects.filter(is_active=True), request.auth, tenant
    )
    return get_object_or_404(queryset, id=objective_id)


@router.post("/strategy/objectives/{objective_id}/key-results")
@require_permission("strategy.change_stgobjective")
def add_key_result_endpoint(
    request: Any, objective_id: str, payload: KeyResultIn
) -> dict[str, Any]:
    objective = _get_objective_in_scope(request, objective_id)
    try:
        key_result = add_key_result(
            objective,
            metric_name=payload.metric_name,
            target_value=payload.target_value,
            unit=payload.unit,
            metric_code=payload.metric_code,
            kpi_source_module=payload.kpi_source_module,
            kpi_source_function=payload.kpi_source_function,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return _serialize_key_result(key_result)


@router.post("/strategy/key-results/{key_result_id}/check-ins")
@require_permission("strategy.change_stgobjective")
def add_check_in_endpoint(request: Any, key_result_id: str, payload: CheckInIn) -> dict[str, Any]:
    key_result = get_object_or_404(StgKeyResult, id=key_result_id)
    _get_objective_in_scope(request, str(key_result.objective_id))
    record_check_in(
        key_result,
        date=payload.date,
        value=payload.value,
        comment=payload.comment,
        author=request.auth,
    )
    key_result.refresh_from_db()
    return _serialize_key_result(key_result)


@router.post("/strategy/key-results/{key_result_id}/refresh")
@require_permission("strategy.change_stgobjective")
def refresh_key_result_endpoint(request: Any, key_result_id: str) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    key_result = get_object_or_404(StgKeyResult, id=key_result_id)
    _get_objective_in_scope(request, str(key_result.objective_id))
    try:
        refresh_key_result_from_source(tenant, key_result)
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return _serialize_key_result(key_result)


@router.get("/strategy/benchmarks")
@require_permission("strategy.view_stgobjective")
def list_benchmarks_endpoint(request: Any, sector_code: str) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    benchmarks = get_benchmarks_for_sector(tenant, sector_code)
    return {"results": [_serialize_benchmark(b) for b in benchmarks]}


@router.post("/strategy/notes")
@require_permission("strategy.add_stgobjective")
def create_note_endpoint(request: Any, payload: NoteIn) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    objective = (
        get_object_or_404(StgObjective, id=payload.objective_id) if payload.objective_id else None
    )
    note = create_note(
        tenant, title=payload.title, body=payload.body, objective=objective, author=request.auth
    )
    return {"id": str(note.id), "title": note.title}


@router.post("/strategy/objectives/{objective_id}/activate")
@require_permission("strategy.change_stgobjective")
def activate_objective_endpoint(request: Any, objective_id: str) -> dict[str, Any]:
    objective = _get_objective_in_scope(request, objective_id)
    try:
        activate_objective(objective)
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return {"id": str(objective.id), "status": objective.status}


@router.get("/strategy/budgets/{budget_id}/variance")
@require_permission("strategy.view_stgbudget")
def get_budget_variance_endpoint(request: Any, budget_id: str) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    budget = get_object_or_404(StgBudget, id=budget_id)
    rows = compute_variance(tenant, budget, user=request.auth)
    return {"results": [serialize_variance_row(row) for row in rows]}


@router.post("/strategy/budgets/{budget_id}/lock")
@require_permission("strategy.change_stgbudget")
def lock_budget_endpoint(request: Any, budget_id: str) -> dict[str, Any]:
    budget = get_object_or_404(StgBudget, id=budget_id)
    try:
        lock_budget(budget, user=request.auth)
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return {"id": str(budget.id), "is_locked": budget.is_locked, "locked_at": budget.locked_at}


@router.get("/strategy/risks")
@require_permission("strategy.view_stgrisk")
def list_risks_endpoint(request: Any) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    risks = StgRisk.objects.filter(tenant=tenant).order_by("-probability", "-impact")
    return {
        "results": [
            {
                "id": str(r.id),
                "title": r.title,
                "probability": r.probability,
                "impact": r.impact,
                "risk_score": r.risk_score,
                "owner_email": r.owner.email if r.owner else "",
                "last_reassessed_at": r.last_reassessed_at,
            }
            for r in risks
        ]
    }


class RiskIn(Schema):
    title: str
    probability: int
    impact: int
    description: str = ""
    control_measure: str = ""


@router.post("/strategy/risks")
@require_permission("strategy.add_stgrisk")
def create_risk_endpoint(request: Any, payload: RiskIn) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    risk = create_risk(
        tenant,
        title=payload.title,
        probability=payload.probability,
        impact=payload.impact,
        description=payload.description,
        control_measure=payload.control_measure,
        owner=request.auth,
        created_by=request.auth,
    )
    return {"id": str(risk.id), "risk_score": risk.risk_score}
