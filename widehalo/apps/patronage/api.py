"""API django-ninja du module `patronage` (§5.4.8)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from apps.core.services.permissions import require_permission
from apps.patronage.models import PatPattern, PatSizeChart
from apps.patronage.services.consumption import compute_consumption, compute_marker, push_to_bom
from apps.patronage.services.eco import EcoApprovalRequiredError, validate_pattern_version
from apps.patronage.services.grading import apply_grading
from apps.patronage.services.patterns import add_pattern_piece, create_pattern, new_pattern_version
from apps.patronage.services.reports import (
    consumption_report,
    marker_report,
    measurement_chart_report,
    rows_to_bytes,
    version_comparison_report,
)
from apps.patronage.services.tech_pack import generate_tech_pack
from apps.patronage.services.variation import variation_points

router = Router(tags=["patronage"])


class PatternIn(Schema):
    code: str
    name: str
    size_chart_id: str


class PieceIn(Schema):
    code: str
    name: str
    qty_per_garment: int = 1
    material_variant_id: str | None = None


class ConsumptionIn(Schema):
    size: str
    material_variant_id: str
    width_cm: Decimal
    waste_pct: Decimal = Decimal(0)


class MarkerIn(Schema):
    material_variant_id: str
    fabric_width_cm: Decimal
    size_ratio: dict[str, int]
    efficiency_pct: Decimal = Decimal(85)


class PushToBomIn(Schema):
    bom_id: str
    material_variant_id: str


def _serialize_pattern(pattern: PatPattern) -> dict[str, Any]:
    return {
        "id": str(pattern.id),
        "code": pattern.code,
        "version": pattern.version,
        "state": pattern.state,
    }


@router.get("/patronage/size-charts")
@require_permission("patronage.view_patsizechart")
def list_size_charts(request):
    return {"results": [{"id": str(s.id), "code": s.code} for s in PatSizeChart.objects.all()]}


@router.post("/patronage/size-charts/{size_chart_id}/grade")
@require_permission("patronage.change_patsizechart")
def grade_size_chart_endpoint(request, size_chart_id: str):
    size_chart = get_object_or_404(PatSizeChart, id=size_chart_id)
    try:
        result = apply_grading(size_chart)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return {
        "results": {code: {s: str(v) for s, v in values.items()} for code, values in result.items()}
    }


@router.get("/patronage/patterns")
@require_permission("patronage.view_patpattern")
def list_patterns(request):
    return {"results": [_serialize_pattern(p) for p in PatPattern.objects.all()]}


@router.post("/patronage/patterns")
@require_permission("patronage.add_patpattern")
def create_pattern_endpoint(request, payload: PatternIn):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    size_chart = get_object_or_404(PatSizeChart, id=payload.size_chart_id)
    pattern = create_pattern(
        tenant=tenant, code=payload.code, name=payload.name, size_chart=size_chart
    )
    return _serialize_pattern(pattern)


@router.post("/patronage/patterns/{pattern_id}/new-version")
@require_permission("patronage.change_patpattern")
def new_version_endpoint(request, pattern_id: str):
    pattern = get_object_or_404(PatPattern, id=pattern_id)
    return _serialize_pattern(new_pattern_version(pattern))


@router.post("/patronage/patterns/{pattern_id}/validate")
@require_permission("patronage.change_patpattern")
def validate_pattern_endpoint(request, pattern_id: str):
    pattern = get_object_or_404(PatPattern, id=pattern_id)
    try:
        validated = validate_pattern_version(pattern, requested_by=request.auth)
    except EcoApprovalRequiredError as exc:
        return JsonResponse({"detail": str(exc), "status": "pending_approval"}, status=202)
    return _serialize_pattern(validated)


@router.get("/patronage/patterns/{pattern_id}/pieces")
@require_permission("patronage.view_patpatternpiece")
def list_pieces_endpoint(request, pattern_id: str):
    pattern = get_object_or_404(PatPattern, id=pattern_id)
    return {
        "results": [{"id": str(p.id), "code": p.code, "name": p.name} for p in pattern.pieces.all()]
    }


@router.post("/patronage/patterns/{pattern_id}/pieces")
@require_permission("patronage.add_patpatternpiece")
def add_piece_endpoint(request, pattern_id: str, payload: PieceIn):
    pattern = get_object_or_404(PatPattern, id=pattern_id)
    try:
        piece = add_pattern_piece(
            pattern,
            code=payload.code,
            name=payload.name,
            qty_per_garment=payload.qty_per_garment,
            material_variant_id=payload.material_variant_id,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return {"id": str(piece.id)}


@router.post("/patronage/patterns/{pattern_id}/compute-consumption")
@require_permission("patronage.add_patconsumption")
def compute_consumption_endpoint(request, pattern_id: str, payload: ConsumptionIn):
    pattern = get_object_or_404(PatPattern, id=pattern_id)
    try:
        consumption = compute_consumption(
            pattern,
            size=payload.size,
            material_variant_id=payload.material_variant_id,
            width_cm=payload.width_cm,
            waste_pct=payload.waste_pct,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return {"id": str(consumption.id), "length_m": str(consumption.length_m)}


@router.post("/patronage/patterns/{pattern_id}/compute-marker")
@require_permission("patronage.add_patmarker")
def compute_marker_endpoint(request, pattern_id: str, payload: MarkerIn):
    pattern = get_object_or_404(PatPattern, id=pattern_id)
    try:
        marker = compute_marker(
            pattern,
            material_variant_id=payload.material_variant_id,
            fabric_width_cm=payload.fabric_width_cm,
            size_ratio=payload.size_ratio,
            efficiency_pct=payload.efficiency_pct,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return {"id": str(marker.id), "length_m": str(marker.length_m)}


# push_to_bom mutates MrpBomLine (via set_bom_line_qty_by_size), not a
# patronage model, even though it hangs off the /patronage/patterns router —
# the permission checked is on the model actually written.
@router.post("/patronage/patterns/{pattern_id}/push-to-bom")
@require_permission("mrp.change_mrpbomline")
def push_to_bom_endpoint(request, pattern_id: str, payload: PushToBomIn):
    pattern = get_object_or_404(PatPattern, id=pattern_id)
    try:
        applied = push_to_bom(
            pattern,
            bom_id=payload.bom_id,
            material_variant_id=payload.material_variant_id,
            actor=request.auth,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return {"applied": applied}


@router.get("/patronage/patterns/{pattern_id}/tech-pack.pdf")
@require_permission("patronage.view_patpattern")
def tech_pack_endpoint(request, pattern_id: str):
    pattern = get_object_or_404(PatPattern, id=pattern_id)
    tech_pack = generate_tech_pack(pattern, actor=request.auth)
    tech_pack.document.file.open("rb")
    data = tech_pack.document.file.read()
    tech_pack.document.file.close()
    response = HttpResponse(data, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{pattern.code}-tech-pack.pdf"'
    return response


@router.get("/patronage/patterns/{pattern_id}/variation-points")
@require_permission("patronage.view_patpattern")
def variation_points_endpoint(request, pattern_id: str):
    pattern = get_object_or_404(PatPattern, id=pattern_id)
    return variation_points(pattern)


@router.get("/patronage/reports/measurements/{pattern_id}")
@require_permission("patronage.view_patsizechart")
def measurements_report_endpoint(request, pattern_id: str, format: str = "json"):
    pattern = get_object_or_404(PatPattern, id=pattern_id)
    rows = measurement_chart_report(pattern)
    fields = ["measurement_point", *pattern.size_chart.sizes]
    return _report_response(rows_to_bytes(rows, fields, format=format), format)


@router.get("/patronage/reports/consumption/{pattern_id}")
@require_permission("patronage.view_patconsumption")
def consumption_report_endpoint(request, pattern_id: str, format: str = "json"):
    pattern = get_object_or_404(PatPattern, id=pattern_id)
    rows = consumption_report(pattern)
    return _report_response(
        rows_to_bytes(
            rows, ["material_variant_id", "size", "length_m", "waste_pct"], format=format
        ),
        format,
    )


@router.get("/patronage/reports/marker/{pattern_id}")
@require_permission("patronage.view_patmarker")
def marker_report_endpoint(request, pattern_id: str, format: str = "json"):
    pattern = get_object_or_404(PatPattern, id=pattern_id)
    rows = marker_report(pattern)
    return _report_response(
        rows_to_bytes(
            rows, ["fabric_width_cm", "size_ratio", "length_m", "efficiency_pct"], format=format
        ),
        format,
    )


@router.get("/patronage/reports/versions/{pattern_id}")
@require_permission("patronage.view_patpattern")
def version_report_endpoint(request, pattern_id: str, format: str = "json"):
    pattern = get_object_or_404(PatPattern, id=pattern_id)
    rows = version_comparison_report(pattern)
    return _report_response(
        rows_to_bytes(rows, ["version", "state", "pieces_count", "date_created"], format=format),
        format,
    )


def _report_response(data: bytes, format: str) -> HttpResponse:
    content_type = {
        "json": "application/json",
        "csv": "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }[format]
    return HttpResponse(data, content_type=content_type)
