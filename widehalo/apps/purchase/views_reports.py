"""Ecrans de telechargement des rapports `purchase` (§5.6.5, PU8),
session-authentifies — meme patron que `apps.sales.views_reports`/
`apps.mrp.views_reports` : les fonctions de `apps.purchase.services.
reports` sont appelees directement (jamais l'API JWT interne)."""

from __future__ import annotations

import uuid

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.core.views.tenant_web import resolve_tenant
from apps.purchase.models import PurOrder, PurRfq
from apps.purchase.services.reports import (
    cri_rows,
    engagements_rows,
    late_orders_rows,
    order_pdf,
    reception_rows,
    rfq_comparison_rows,
    rfq_rows,
    rows_to_bytes,
    supplier_evaluation_rows,
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
    return render(request, "purchase/reports.html", {})


@login_required
def report_order_pdf(request: HttpRequest, order_id: str) -> HttpResponse:
    """PUR-BC."""
    order = get_object_or_404(PurOrder, id=order_id)
    pdf_bytes = order_pdf(order)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    filename = order.reference or str(order.id)
    response["Content-Disposition"] = f'attachment; filename="{filename}.pdf"'
    return response


@login_required
def report_rfq(request: HttpRequest, rfq_id: str) -> HttpResponse:
    """PUR-RFQ."""
    rfq = get_object_or_404(PurRfq, id=rfq_id)
    format = request.GET.get("format", "json")
    rows = rfq_rows(rfq)
    data = rows_to_bytes(
        rows,
        ["variant_id", "description", "qty", "uom", "suppliers_consulted", "responses_received"],
        format=format,
    )
    return _report_response(data, format, f"appel-offres-{rfq.reference or rfq.id}")


@login_required
def report_rfq_comparison(request: HttpRequest, rfq_id: str) -> HttpResponse:
    """PUR-COMP."""
    rfq = get_object_or_404(PurRfq, id=rfq_id)
    format = request.GET.get("format", "json")
    rows = rfq_comparison_rows(rfq)
    data = rows_to_bytes(
        rows,
        ["response_id", "partner_id", "total_mga", "lead_time_days", "validity_date", "score"],
        format=format,
    )
    return _report_response(data, format, f"comparatif-{rfq.reference or rfq.id}")


@login_required
def report_reception(request: HttpRequest, order_id: str) -> HttpResponse:
    """PUR-REC."""
    order = get_object_or_404(PurOrder, id=order_id)
    format = request.GET.get("format", "json")
    rows = reception_rows(order)
    data = rows_to_bytes(
        rows,
        ["date", "order_line_id", "description", "qty_received", "quality_status", "notes"],
        format=format,
    )
    return _report_response(data, format, f"reception-{order.reference or order.id}")


@login_required
def report_engagements(request: HttpRequest) -> HttpResponse:
    """PUR-ENG."""
    tenant = resolve_tenant(request)
    format = request.GET.get("format", "json")
    rows = engagements_rows(tenant)
    data = rows_to_bytes(
        rows,
        ["partner_id", "reference", "state", "amount_total_mga", "date_expected"],
        format=format,
    )
    return _report_response(data, format, "achats-engagements")


@login_required
def report_supplier_evaluations(request: HttpRequest) -> HttpResponse:
    """PUR-EVAL."""
    format = request.GET.get("format", "json")
    partner_id = request.GET.get("partner_id", "")
    rows = supplier_evaluation_rows(uuid.UUID(partner_id)) if partner_id else []
    data = rows_to_bytes(
        rows,
        [
            "date",
            "score_quantity",
            "score_quality",
            "score_cost",
            "score_delay",
            "score_conformity",
            "weighted_score",
            "notes",
        ],
        format=format,
    )
    return _report_response(data, format, "achats-evaluations-fournisseurs")


@login_required
def report_late_orders(request: HttpRequest) -> HttpResponse:
    """PUR-RET."""
    tenant = resolve_tenant(request)
    format = request.GET.get("format", "json")
    rows = late_orders_rows(tenant)
    data = rows_to_bytes(
        rows, ["reference", "partner_id", "date_expected", "state", "days_late"], format=format
    )
    return _report_response(data, format, "achats-retards")


@login_required
def report_cri(request: HttpRequest) -> HttpResponse:
    """PUR-CRI."""
    tenant = resolve_tenant(request)
    format = request.GET.get("format", "json")
    state = request.GET.get("state", "")
    type = request.GET.get("type", "")  # noqa: A001 - coherent avec PurCri.type
    rows = cri_rows(tenant, state=state, type=type)
    data = rows_to_bytes(
        rows,
        [
            "reference",
            "date",
            "type",
            "partner_id",
            "order_reference",
            "description",
            "impact",
            "cost_mga",
            "state",
        ],
        format=format,
    )
    return _report_response(data, format, "achats-incidents")
