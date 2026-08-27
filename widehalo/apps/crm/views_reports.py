"""Ecran de rapports du module `crm` (U5) : expose en session/HTML les
fonctions de `apps.crm.services.reports` — jusqu'ici accessibles
uniquement via l'API ninja (authentification JWT), donc injoignables depuis
une session navigateur classique. Meme patron que `apps.crm.views` :
chaque vue appelle directement les fonctions de service, jamais l'API
ninja."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.core.views.tenant_web import resolve_tenant
from apps.crm.models import CrmPipeline
from apps.crm.services.reports import (
    activity_breakdown,
    conversion_rate,
    lost_reason_breakdown,
    pipeline_breakdown,
    rows_to_bytes,
)

CONTENT_TYPES = {
    "json": "application/json",
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _report_response(data: bytes, format: str, filename: str) -> HttpResponse:
    response = HttpResponse(
        data, content_type=CONTENT_TYPES.get(format, "application/octet-stream")
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}.{format}"'
    return response


@login_required
def reports_index(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    return render(
        request,
        "crm/reports.html",
        {"pipelines": CrmPipeline.objects.filter(tenant=tenant).order_by("name")},
    )


@login_required
def pipeline_report_download(request: HttpRequest) -> HttpResponse:
    pipeline = get_object_or_404(CrmPipeline, id=request.GET.get("pipeline_id"))
    format = request.GET.get("format", "json")
    rows = pipeline_breakdown(pipeline)
    data = rows_to_bytes(
        rows,
        ["stage_code", "stage_name", "lead_count", "total_expected_revenue_mga"],
        format=format,
    )
    return _report_response(data, format, "pipeline")


@login_required
def conversion_report_download(request: HttpRequest) -> HttpResponse:
    pipeline = get_object_or_404(CrmPipeline, id=request.GET.get("pipeline_id"))
    format = request.GET.get("format", "json")
    rows = [conversion_rate(pipeline)]
    data = rows_to_bytes(rows, ["won", "lost", "closed", "conversion_rate_pct"], format=format)
    return _report_response(data, format, "conversion")


@login_required
def activities_report_download(request: HttpRequest) -> HttpResponse:
    format = request.GET.get("format", "json")
    rows = activity_breakdown()
    data = rows_to_bytes(rows, ["activity_type", "count"], format=format)
    return _report_response(data, format, "activites")


@login_required
def lost_report_download(request: HttpRequest) -> HttpResponse:
    format = request.GET.get("format", "json")
    rows = lost_reason_breakdown()
    data = rows_to_bytes(
        rows, ["lost_reason", "lead_count", "total_expected_revenue_mga"], format=format
    )
    return _report_response(data, format, "motifs-perte")
