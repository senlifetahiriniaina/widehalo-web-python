"""Ecrans de telechargement des rapports `stocks` (§5.8.5, ST8),
session-authentifies — meme patron que `apps.purchase.views_reports`/
`apps.sales.views_reports` : les fonctions de `apps.stocks.services.reports`
sont appelees directement (jamais l'API JWT interne). L'index (liens de
telechargement) est une SECTION du gabarit unique `stocks/index.html`
(`active_tab="reports"`) — les telechargements eux-memes renvoient des
octets bruts (`HttpResponse`), jamais un gabarit, donc n'entament pas le
budget d'ecrans (cf. docstring `apps.stocks.views`)."""

from __future__ import annotations

import uuid

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.core.views.tenant_web import resolve_tenant
from apps.stocks.models import StkInventory, StkLot
from apps.stocks.services.reports import (
    defect_analysis_rows,
    dormant_stock_rows,
    inventory_line_rows,
    measurement_variance_rows,
    move_rows,
    production_consistency_rows,
    rows_to_bytes,
    stock_state_rows,
    traceability_rows,
    valuation_layer_rows,
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
    return render(request, "stocks/index.html", {"active_tab": "reports"})


@login_required
def report_state(request: HttpRequest) -> HttpResponse:
    """STK-ETAT."""
    tenant = resolve_tenant(request)
    format = request.GET.get("format", "json")
    rows = stock_state_rows(tenant)
    data = rows_to_bytes(rows, ["location_id", "variant_id", "qty", "value_mga"], format=format)
    return _report_response(data, format, "stocks-etat")


@login_required
def report_moves(request: HttpRequest) -> HttpResponse:
    """STK-MOUV."""
    from django.utils.dateparse import parse_date

    tenant = resolve_tenant(request)
    format = request.GET.get("format", "json")
    variant_raw = request.GET.get("variant_id", "")
    rows = move_rows(
        tenant,
        date_from=parse_date(request.GET.get("date_from", "")),
        date_to=parse_date(request.GET.get("date_to", "")),
        variant_id=uuid.UUID(variant_raw) if variant_raw else None,
        move_type=request.GET.get("move_type", ""),
    )
    data = rows_to_bytes(
        rows,
        [
            "reference",
            "date",
            "move_type",
            "state",
            "variant_id",
            "lot_id",
            "qty",
            "uom",
            "location_from_id",
            "location_to_id",
            "unit_cost_mga",
            "value_mga",
            "source_document",
        ],
        format=format,
    )
    return _report_response(data, format, "stocks-mouvements")


@login_required
def report_traceability(request: HttpRequest, lot_id: str) -> HttpResponse:
    """STK-TRAC."""
    lot = get_object_or_404(StkLot, id=lot_id)
    format = request.GET.get("format", "json")
    rows = traceability_rows(lot)
    data = rows_to_bytes(
        rows,
        [
            "direction",
            "move_id",
            "reference",
            "date",
            "move_type",
            "qty",
            "location_from_id",
            "location_to_id",
            "source_document",
            "location_id",
            "qty_location",
        ],
        format=format,
    )
    return _report_response(data, format, f"stocks-tracabilite-{lot.name}")


@login_required
def report_inventory(request: HttpRequest, inventory_id: str) -> HttpResponse:
    """STK-INV."""
    inventory = get_object_or_404(StkInventory, id=inventory_id)
    format = request.GET.get("format", "json")
    rows = inventory_line_rows(inventory)
    data = rows_to_bytes(
        rows,
        [
            "variant_id",
            "lot_id",
            "location_id",
            "qty_theoretical",
            "qty_counted",
            "difference",
            "reason",
        ],
        format=format,
    )
    filename = f"stocks-inventaire-{inventory.reference or inventory.id}"
    return _report_response(data, format, filename)


@login_required
def report_defects(request: HttpRequest) -> HttpResponse:
    """STK-DEF."""
    tenant = resolve_tenant(request)
    format = request.GET.get("format", "json")
    rows = defect_analysis_rows(tenant)
    data = rows_to_bytes(
        rows,
        ["defect_type_code", "defect_type_name", "category", "state", "total_qty", "count"],
        format=format,
    )
    return _report_response(data, format, "stocks-defauts")


@login_required
def report_dormant(request: HttpRequest) -> HttpResponse:
    """STK-AGE."""
    tenant = resolve_tenant(request)
    format = request.GET.get("format", "json")
    rows = dormant_stock_rows(tenant)
    data = rows_to_bytes(
        rows,
        ["variant_id", "location_id", "qty", "value_mga", "days_since_last_movement", "is_dormant"],
        format=format,
    )
    return _report_response(data, format, "stocks-obsolescence")


@login_required
def report_consistency(request: HttpRequest) -> HttpResponse:
    """STK-COHER."""
    tenant = resolve_tenant(request)
    format = request.GET.get("format", "json")
    rows = production_consistency_rows(tenant)
    data = rows_to_bytes(
        rows,
        [
            "order_id",
            "order_reference",
            "workshop_id",
            "qty_declared",
            "qty_entered_stock",
            "variance",
            "anomaly",
        ],
        format=format,
    )
    return _report_response(data, format, "stocks-coherence-production")


@login_required
def report_measurements(request: HttpRequest) -> HttpResponse:
    """STK-MES."""
    tenant = resolve_tenant(request)
    format = request.GET.get("format", "json")
    rows = measurement_variance_rows(tenant)
    data = rows_to_bytes(
        rows, ["measured_at", "type", "value", "uom", "variance_pct", "device"], format=format
    )
    return _report_response(data, format, "stocks-ecarts-mesure")


@login_required
def report_valuation(request: HttpRequest) -> HttpResponse:
    """STK-VAL."""
    tenant = resolve_tenant(request)
    format = request.GET.get("format", "json")
    variant_raw = request.GET.get("variant_id", "")
    rows = valuation_layer_rows(tenant, variant_id=uuid.UUID(variant_raw) if variant_raw else None)
    data = rows_to_bytes(
        rows,
        [
            "variant_id",
            "date",
            "qty",
            "unit_cost_mga",
            "value_mga",
            "remaining_qty",
            "remaining_value_mga",
        ],
        format=format,
    )
    return _report_response(data, format, "stocks-valorisation")
