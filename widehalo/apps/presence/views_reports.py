"""Ecran de telechargement des rapports `presence` (§5.9.6), meme patron
que `apps.logistics.views_reports`."""

from __future__ import annotations

import datetime as dt

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.core.views.tenant_web import resolve_tenant
from apps.presence.services.reports import (
    absence_register_rows,
    absenteeism_by_department_rows,
    attendance_sheet_rows,
    leave_balance_rows,
    overtime_rows,
    reconciliation_rows,
    rows_to_bytes,
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


def _period(request: HttpRequest) -> tuple[int, int]:
    today = dt.date.today()
    year = int(request.GET.get("year", today.year))
    month = int(request.GET.get("month", today.month))
    return year, month


@login_required
def reports_index(request: HttpRequest) -> HttpResponse:
    return render(request, "presence/reports.html", {})


@login_required
def report_attendance_sheet(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    format = request.GET.get("format", "json")
    year, month = _period(request)
    rows = attendance_sheet_rows(tenant, year=year, month=month)
    data = rows_to_bytes(
        rows,
        [
            "employee_reference",
            "employee_name",
            "date",
            "check_in",
            "check_out",
            "mode",
            "worked_minutes",
            "late_minutes",
            "overtime_minutes",
        ],
        format=format,
    )
    return _report_response(data, format, "presence-feuille-pointage")


@login_required
def report_absences(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    format = request.GET.get("format", "json")
    rows = absence_register_rows(tenant)
    data = rows_to_bytes(
        rows,
        ["reference", "employee_name", "type", "date_from", "date_to", "days_count", "state"],
        format=format,
    )
    return _report_response(data, format, "presence-registre-absences")


@login_required
def report_leave_balances(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    format = request.GET.get("format", "json")
    year = int(request.GET.get("year", dt.date.today().year))
    rows = leave_balance_rows(tenant, year=year)
    data = rows_to_bytes(
        rows,
        [
            "employee_name",
            "type",
            "acquired_days",
            "taken_days",
            "pending_days",
            "remaining_days",
            "expiry_date",
        ],
        format=format,
    )
    return _report_response(data, format, "presence-soldes-conges")


@login_required
def report_overtime(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    format = request.GET.get("format", "json")
    year, month = _period(request)
    rows = overtime_rows(tenant, year=year, month=month)
    data = rows_to_bytes(
        rows, ["employee_name", "date", "hours", "rate_category", "state"], format=format
    )
    return _report_response(data, format, "presence-heures-supplementaires")


@login_required
def report_absenteeism(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    format = request.GET.get("format", "json")
    year, month = _period(request)
    rows = absenteeism_by_department_rows(tenant, year=year, month=month)
    data = rows_to_bytes(rows, ["department", "employee_count", "absence_days"], format=format)
    return _report_response(data, format, "presence-taux-absenteisme")


@login_required
def report_reconciliation(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    format = request.GET.get("format", "json")
    year, month = _period(request)
    rows = reconciliation_rows(tenant, year=year, month=month)
    data = rows_to_bytes(
        rows,
        ["employee_name", "presence_hours", "cra_hours", "deviation_pct", "flagged"],
        format=format,
    )
    return _report_response(data, format, "presence-coherence-cra")
