"""API django-ninja du module `feasibility` (etudes de faisabilite, FEA1-3).
CRUD etudes + lignes + declenchement de simulation — la generation du
rapport PDF reste geree par le catalogue `reporting` (`POST /reporting/
generate` avec `code=FEA-STUDY`), pas un endpoint dedie ici (coherent avec
STRATEGY-BP/FIN-DOSSIER, jamais un second mecanisme de generation de
rapport)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from apps.core.models.tenant import Tenant
from apps.core.services.permissions import require_permission
from apps.feasibility.models import FeaStudy, FeaStudyLine
from apps.feasibility.services.simulation import add_study_line, create_study, simulate_study_line

router = Router(tags=["feasibility"])


class StudyIn(Schema):
    name: str
    description: str = ""
    sector_code: str = ""
    owner_id: str | None = None


class StudyLineIn(Schema):
    variant_id: str | None = None
    hypothetical_spec: dict[str, Any] = {}
    assumed_qty: Decimal = Decimal(1)
    assumed_unit_price_mga: Decimal = Decimal(0)


class SimulateIn(Schema):
    component_unit_costs: dict[str, Decimal] = {}
    overhead_rate_pct: Decimal = Decimal(0)


def _serialize_study(study: FeaStudy) -> dict[str, Any]:
    return {
        "id": str(study.id),
        "reference": study.reference,
        "name": study.name,
        "description": study.description,
        "sector_code": study.sector_code,
        "status": study.status,
        "owner_id": str(study.owner_id) if study.owner_id else None,
        "total_cost_mga": str(study.total_cost_mga()),
        "total_revenue_mga": str(study.total_revenue_mga()),
    }


def _serialize_line(line: FeaStudyLine) -> dict[str, Any]:
    return {
        "id": str(line.id),
        "variant_id": str(line.variant_id) if line.variant_id else None,
        "hypothetical_spec": line.hypothetical_spec,
        "assumed_qty": str(line.assumed_qty),
        "assumed_unit_price_mga": str(line.assumed_unit_price_mga),
        "cost_breakdown": line.cost_breakdown,
        "computed_margin_pct": str(line.computed_margin_pct),
    }


@router.get("/feasibility/studies")
@require_permission("feasibility.view_feastudy")
def list_studies_endpoint(request: Any) -> dict[str, Any]:
    studies = FeaStudy.objects.filter(is_active=True)
    return {"results": [_serialize_study(s) for s in studies]}


@router.post("/feasibility/studies")
@require_permission("feasibility.add_feastudy")
def create_study_endpoint(request: Any, payload: StudyIn) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    owner = None
    if payload.owner_id:
        from apps.core.models.user import User

        owner = get_object_or_404(User, id=payload.owner_id)
    study = create_study(
        tenant,
        name=payload.name,
        description=payload.description,
        sector_code=payload.sector_code,
        owner=owner,
        created_by=request.auth,
    )
    return _serialize_study(study)


@router.get("/feasibility/studies/{study_id}")
@require_permission("feasibility.view_feastudy")
def study_detail_endpoint(request: Any, study_id: str) -> dict[str, Any]:
    study = get_object_or_404(FeaStudy, id=study_id)
    lines = [_serialize_line(line) for line in study.lines.all()]
    return {**_serialize_study(study), "lines": lines}


@router.post("/feasibility/studies/{study_id}/lines")
@require_permission("feasibility.change_feastudy")
def add_study_line_endpoint(request: Any, study_id: str, payload: StudyLineIn) -> dict[str, Any]:
    study = get_object_or_404(FeaStudy, id=study_id)
    line = add_study_line(
        study,
        variant_id=UUID(payload.variant_id) if payload.variant_id else None,
        hypothetical_spec=payload.hypothetical_spec,
        assumed_qty=payload.assumed_qty,
        assumed_unit_price_mga=payload.assumed_unit_price_mga,
    )
    return _serialize_line(line)


@router.post("/feasibility/lines/{line_id}/simulate")
@require_permission("feasibility.change_feastudy")
def simulate_line_endpoint(request: Any, line_id: str, payload: SimulateIn) -> dict[str, Any]:
    line = get_object_or_404(FeaStudyLine, id=line_id)
    # Cles JSON forcement `str` (UUID non serialisable en cle JSON) —
    # reconverties en `UUID` pour matcher `component_template_id` (UUID)
    # renvoye par `mrp.services.bom.explode()`.
    component_unit_costs = {
        UUID(component_id): cost for component_id, cost in payload.component_unit_costs.items()
    }
    line = simulate_study_line(
        line,
        component_unit_costs=component_unit_costs,
        overhead_rate_pct=payload.overhead_rate_pct,
    )
    return _serialize_line(line)
