"""Ecrans de telechargement des rapports `sales` (§5.5.7, S7), session-
authentifies — meme patron que `apps.mrp.views_reports` : les fonctions de
`apps.sales.services.reports` sont appelees directement (jamais l'API JWT
interne)."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.core.services.permissions import user_role_codes
from apps.sales.models import SalesOrder, SalesQuotation
from apps.sales.services.reports import (
    delivery_note_rows,
    forecast_rows,
    late_orders_report,
    margin_report,
    order_confirmation_pdf,
    quotation_pdf,
    revenue_report,
    rows_to_bytes,
    target_achievement_report,
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


def _period_from_request(request: HttpRequest) -> tuple:  # type: ignore[type-arg]
    today = timezone.now().date()
    date_from = parse_date(request.GET.get("date_from", "")) or today.replace(day=1)
    date_to = parse_date(request.GET.get("date_to", "")) or today
    format = request.GET.get("format", "json")
    return date_from, date_to, format


@login_required
def reports_index(request: HttpRequest) -> HttpResponse:
    return render(request, "sales/reports.html", {})


@login_required
def report_quotation_pdf(request: HttpRequest, quotation_id: str) -> HttpResponse:
    """SAL-DEVIS."""
    quotation = get_object_or_404(SalesQuotation, id=quotation_id)
    pdf_bytes = quotation_pdf(quotation)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    filename = quotation.reference or str(quotation.id)
    response["Content-Disposition"] = f'attachment; filename="{filename}.pdf"'
    return response


@login_required
def report_order_confirmation_pdf(request: HttpRequest, order_id: str) -> HttpResponse:
    """SAL-BC."""
    order = get_object_or_404(SalesOrder, id=order_id)
    pdf_bytes = order_confirmation_pdf(order)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    filename = order.reference or str(order.id)
    response["Content-Disposition"] = f'attachment; filename="{filename}.pdf"'
    return response


@login_required
def report_delivery_note(request: HttpRequest, order_id: str) -> HttpResponse:
    """SAL-BL (portee minimale assumee, cf. `services.reports.
    delivery_note_rows`)."""
    order = get_object_or_404(SalesOrder, id=order_id)
    format = request.GET.get("format", "json")
    rows = delivery_note_rows(order)
    data = rows_to_bytes(
        rows, ["description", "qty_ordered", "qty_delivered", "uom"], format=format
    )
    return _report_response(data, format, f"bl-{order.reference or order.id}")


@login_required
def report_revenue(request: HttpRequest) -> HttpResponse:
    """SAL-CA."""
    date_from, date_to, format = _period_from_request(request)
    group_by = request.GET.get("group_by", "partner_id")
    rows = revenue_report(date_from=date_from, date_to=date_to, group_by=group_by)
    fields = ["salesperson", "total_mga"] if group_by == "salesperson" else [group_by, "total_mga"]
    data = rows_to_bytes(rows, fields, format=format)
    return _report_response(data, format, "sales-ca")


@login_required
def report_margin(request: HttpRequest) -> HttpResponse:
    """SAL-MARGE — RG-SAL-5 : masquage applique dans
    `services.reports.margin_report` selon les roles de l'utilisateur
    courant (memes roles que l'ecran/l'API)."""
    format = request.GET.get("format", "json")
    role_codes = user_role_codes(request.user)
    rows = margin_report(role_codes=role_codes)
    can_see_margin = bool(role_codes & {"direction", "admin", "resp_commercial"})
    fields = ["order_reference", "description", "subtotal"]
    if can_see_margin:
        fields += ["margin_pct", "cost_estimate_mga"]
    data = rows_to_bytes(rows, fields, format=format)
    return _report_response(data, format, "sales-marge")


@login_required
def report_late_orders(request: HttpRequest) -> HttpResponse:
    """SAL-RET."""
    format = request.GET.get("format", "json")
    rows = late_orders_report()
    data = rows_to_bytes(
        rows, ["reference", "partner_id", "commitment_date", "state", "days_late"], format=format
    )
    return _report_response(data, format, "sales-retards")


@login_required
def report_targets(request: HttpRequest) -> HttpResponse:
    """SAL-OBJ."""
    format = request.GET.get("format", "json")
    period = request.GET.get("period") or timezone.now().strftime("%Y-%m")
    rows = target_achievement_report(period=period)
    data = rows_to_bytes(
        rows,
        ["scope", "scope_ref", "target_mga", "realized_mga", "achievement_pct"],
        format=format,
    )
    return _report_response(data, format, f"sales-objectifs-{period}")


@login_required
def report_forecast(request: HttpRequest) -> HttpResponse:
    """SAL-PREV."""
    format = request.GET.get("format", "json")
    today = timezone.now().date()
    date_from = request.GET.get("date_from") or today.replace(day=1).strftime("%Y-%m")
    date_to = request.GET.get("date_to") or today.strftime("%Y-%m")
    rows = forecast_rows(date_from=date_from, date_to=date_to)
    data = rows_to_bytes(
        rows,
        [
            "period",
            "variant_id",
            "partner_id",
            "qty_forecast",
            "qty_actual",
            "confidence",
            "method",
        ],
        format=format,
    )
    return _report_response(data, format, "sales-previsions")
