"""Ecran de telechargement des rapports `logistics` (§5.7, LOG7),
session-authentifie — meme patron que `apps.purchase.views_reports`/
`apps.sales.views_reports` : les fonctions de `apps.logistics.services.
reports` sont appelees directement (jamais l'API JWT interne)."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.core.views.tenant_web import resolve_tenant
from apps.logistics.services.reports import (
    customs_duty_rows,
    rows_to_bytes,
    shipment_status_rows,
    vehicle_cost_rows,
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
def reports_index(request: HttpRequest) -> HttpResponse:
    return render(request, "logistics/reports.html", {})


@login_required
def report_vehicle_costs(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    format = request.GET.get("format", "json")
    rows = vehicle_cost_rows(tenant)
    data = rows_to_bytes(
        rows,
        ["vehicle_plate_number", "cost_type", "total_amount_mga", "entry_count"],
        format=format,
    )
    return _report_response(data, format, "logistique-couts-vehicules")


@login_required
def report_shipments(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    format = request.GET.get("format", "json")
    rows = shipment_status_rows(tenant)
    data = rows_to_bytes(
        rows,
        ["reference", "origin", "destination", "state", "carrier_id", "freight_cost_mga"],
        format=format,
    )
    return _report_response(data, format, "logistique-expeditions")


@login_required
def report_customs(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    format = request.GET.get("format", "json")
    rows = customs_duty_rows(tenant)
    data = rows_to_bytes(
        rows,
        [
            "customs_file_reference",
            "hs_code",
            "description",
            "caf_value_mga",
            "duty_mga",
            "vat_mga",
            "landed_cost_mga",
        ],
        format=format,
    )
    return _report_response(data, format, "logistique-droits-de-douane")
