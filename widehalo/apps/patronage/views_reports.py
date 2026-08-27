"""Ecrans de telechargement des rapports patronage (§5.4.7), session-
authentifies (U5) : les fonctions de `apps.patronage.services.reports` sont
deja exposees par l'API ninja (JWT), mais inaccessibles depuis une session
HTML normale — ces vues appellent directement le service, comme le reste du
module (jamais d'appel interne a l'API)."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404

from apps.patronage.models import PatPattern
from apps.patronage.services.reports import (
    consumption_report,
    marker_report,
    measurement_chart_report,
    rows_to_bytes,
    version_comparison_report,
)

_CONTENT_TYPES = {
    "json": "application/json",
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

_EXTENSIONS = {"json": "json", "csv": "csv", "xlsx": "xlsx"}


def _report_response(data: bytes, format: str, filename: str) -> HttpResponse:
    response = HttpResponse(data, content_type=_CONTENT_TYPES[format])
    response["Content-Disposition"] = f'attachment; filename="{filename}.{_EXTENSIONS[format]}"'
    return response


@login_required
def report_measurements(request: HttpRequest, pattern_id: str) -> HttpResponse:
    pattern = get_object_or_404(PatPattern, id=pattern_id)
    format = request.GET.get("format", "json")
    rows = measurement_chart_report(pattern)
    fields = ["measurement_point", *pattern.size_chart.sizes]
    data = rows_to_bytes(rows, fields, format=format)
    return _report_response(data, format, f"{pattern.code}-mesures")


@login_required
def report_consumption(request: HttpRequest, pattern_id: str) -> HttpResponse:
    pattern = get_object_or_404(PatPattern, id=pattern_id)
    format = request.GET.get("format", "json")
    rows = consumption_report(pattern)
    data = rows_to_bytes(
        rows, ["material_variant_id", "size", "length_m", "waste_pct"], format=format
    )
    return _report_response(data, format, f"{pattern.code}-consommation")


@login_required
def report_marker(request: HttpRequest, pattern_id: str) -> HttpResponse:
    pattern = get_object_or_404(PatPattern, id=pattern_id)
    format = request.GET.get("format", "json")
    rows = marker_report(pattern)
    data = rows_to_bytes(
        rows, ["fabric_width_cm", "size_ratio", "length_m", "efficiency_pct"], format=format
    )
    return _report_response(data, format, f"{pattern.code}-plan-de-coupe")


@login_required
def report_versions(request: HttpRequest, pattern_id: str) -> HttpResponse:
    pattern = get_object_or_404(PatPattern, id=pattern_id)
    format = request.GET.get("format", "json")
    rows = version_comparison_report(pattern)
    data = rows_to_bytes(rows, ["version", "state", "pieces_count", "date_created"], format=format)
    return _report_response(data, format, f"{pattern.code}-versions")
