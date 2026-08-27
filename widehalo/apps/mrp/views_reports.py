"""Ecrans de telechargement des rapports MRP (§5.3.6), session-authentifies
(U5) : les fonctions de `apps.mrp.services.reports` sont deja exposees par
l'API ninja (JWT), mais inaccessibles depuis une session HTML normale — ces
vues appellent directement le service, comme le reste du module (jamais
d'appel interne a l'API)."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.mrp.models import MrpOrder, MrpWorkshop
from apps.mrp.services.reports import (
    cost_report,
    cra_summary,
    cri_summary,
    efficiency_report,
    order_pdf,
    rows_to_bytes,
    scrap_report,
    workload_report,
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


def _period_from_request(request: HttpRequest) -> tuple:
    today = timezone.now().date()
    date_from = parse_date(request.GET.get("date_from", "")) or today.replace(day=1)
    date_to = parse_date(request.GET.get("date_to", "")) or today
    format = request.GET.get("format", "json")
    return date_from, date_to, format


@login_required
def reports_index(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "mrp/reports.html",
        {
            "workshops": MrpWorkshop.objects.filter(is_active=True),
        },
    )


@login_required
def report_order_pdf(request: HttpRequest, order_id: str) -> HttpResponse:
    order = get_object_or_404(MrpOrder, id=order_id)
    pdf_bytes = order_pdf(order)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    filename = order.reference or str(order.id)
    response["Content-Disposition"] = f'attachment; filename="{filename}.pdf"'
    return response


@login_required
def report_cost(request: HttpRequest, order_id: str) -> HttpResponse:
    order = get_object_or_404(MrpOrder, id=order_id)
    format = request.GET.get("format", "json")
    row = cost_report(order)
    data = rows_to_bytes([row], list(row.keys()), format=format)
    return _report_response(data, format, f"cout-{order.reference or order.id}")


@login_required
def report_cra(request: HttpRequest) -> HttpResponse:
    date_from, date_to, format = _period_from_request(request)
    rows = cra_summary(date_from=date_from, date_to=date_to)
    data = rows_to_bytes(
        rows, ["employee", "workshop", "state", "total_hours", "total_qty_done"], format=format
    )
    return _report_response(data, format, "mrp-cra")


@login_required
def report_cri(request: HttpRequest) -> HttpResponse:
    date_from, date_to, format = _period_from_request(request)
    rows = cri_summary(date_from=date_from, date_to=date_to)
    data = rows_to_bytes(rows, ["workcenter", "type", "total_downtime_min", "count"], format=format)
    return _report_response(data, format, "mrp-cri")


@login_required
def report_efficiency(request: HttpRequest) -> HttpResponse:
    workcenter_code = request.GET.get("workcenter_code") or None
    format = request.GET.get("format", "json")
    rows = efficiency_report(workcenter_code)
    data = rows_to_bytes(
        rows, ["workcenter", "qty_done", "qty_rejected", "efficiency_pct"], format=format
    )
    return _report_response(data, format, "mrp-efficacite")


@login_required
def report_scrap(request: HttpRequest) -> HttpResponse:
    date_from, date_to, format = _period_from_request(request)
    rows = scrap_report(date_from=date_from, date_to=date_to)
    data = rows_to_bytes(rows, ["reason", "total_qty", "total_cost_mga"], format=format)
    return _report_response(data, format, "mrp-rebuts")


@login_required
def report_workload(request: HttpRequest, workshop_id: str) -> HttpResponse:
    workshop = get_object_or_404(MrpWorkshop, id=workshop_id)
    format = request.GET.get("format", "json")
    rows = workload_report(workshop)
    data = rows_to_bytes(rows, ["workcenter", "total_planned_min"], format=format)
    return _report_response(data, format, f"mrp-charge-{workshop.code}")
