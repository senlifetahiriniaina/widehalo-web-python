"""Rapports `presence` (§5.9.6) : PRS-POINT (feuille de pointage
mensuelle), PRS-ABS (registre des absences), PRS-SOLDE (soldes de
congés), PRS-HSUP (heures supplémentaires par catégorie), PRS-ABSENT (taux
d'absentéisme par département), PRS-COHER (écart présence/CRA).

`rows_to_bytes` est une COPIE volontaire du helper identique de
`apps.logistics.services.reports`/`apps.purchase.services.reports`/etc.
(deja duplique par app dans ce projet, jamais centralise dans `core`) —
suivre la convention existante."""

from __future__ import annotations

import csv
import io
import json
from typing import TYPE_CHECKING, Any

from apps.presence.models import (
    PrsAbsence,
    PrsAttendance,
    PrsEmployee,
    PrsLeaveBalance,
    PrsOvertime,
)
from apps.presence.services.reconciliation import reconcile_month

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant


def rows_to_bytes(rows: list[dict[str, Any]], fields: list[str], *, format: str = "json") -> bytes:
    if format == "json":
        return json.dumps(rows, indent=2, ensure_ascii=False, default=str).encode("utf-8")

    if format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        return buffer.getvalue().encode("utf-8")

    if format == "xlsx":
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(fields)
        for row in rows:
            sheet.append([row.get(field) for field in fields])
        buffer_bytes = io.BytesIO()
        workbook.save(buffer_bytes)
        return buffer_bytes.getvalue()

    raise ValueError(f"Format d'export non supporte : {format}")


def attendance_sheet_rows(tenant: Tenant, *, year: int, month: int) -> list[dict[str, Any]]:
    """PRS-POINT : feuille de pointage mensuelle, une ligne par pointage."""
    attendances = (
        PrsAttendance.objects.filter(
            tenant=tenant, is_active=True, date__year=year, date__month=month
        )
        .select_related("employee")
        .order_by("employee__last_name", "date")
    )
    return [
        {
            "employee_reference": attendance.employee.reference,
            "employee_name": str(attendance.employee),
            "date": attendance.date,
            "check_in": attendance.check_in,
            "check_out": attendance.check_out,
            "mode": attendance.mode,
            "worked_minutes": attendance.worked_minutes,
            "late_minutes": attendance.late_minutes,
            "overtime_minutes": attendance.overtime_minutes,
        }
        for attendance in attendances
    ]


def absence_register_rows(tenant: Tenant) -> list[dict[str, Any]]:
    """PRS-ABS : registre des absences."""
    absences = (
        PrsAbsence.objects.filter(tenant=tenant, is_active=True)
        .select_related("employee", "type")
        .order_by("-date_from")
    )
    return [
        {
            "reference": absence.reference,
            "employee_name": str(absence.employee),
            "type": absence.type.name,
            "date_from": absence.date_from,
            "date_to": absence.date_to,
            "days_count": absence.days_count,
            "state": absence.state,
        }
        for absence in absences
    ]


def leave_balance_rows(tenant: Tenant, *, year: int) -> list[dict[str, Any]]:
    """PRS-SOLDE : soldes de congés."""
    balances = (
        PrsLeaveBalance.objects.filter(tenant=tenant, is_active=True, year=year)
        .select_related("employee", "type")
        .order_by("employee__last_name")
    )
    return [
        {
            "employee_name": str(balance.employee),
            "type": balance.type.name,
            "acquired_days": balance.acquired_days,
            "taken_days": balance.taken_days,
            "pending_days": balance.pending_days,
            "remaining_days": balance.remaining_days,
            "expiry_date": balance.expiry_date,
        }
        for balance in balances
    ]


def overtime_rows(tenant: Tenant, *, year: int, month: int) -> list[dict[str, Any]]:
    """PRS-HSUP : heures supplémentaires par catégorie."""
    overtimes = (
        PrsOvertime.objects.filter(
            tenant=tenant, is_active=True, date__year=year, date__month=month
        )
        .select_related("employee")
        .order_by("employee__last_name", "date")
    )
    return [
        {
            "employee_name": str(overtime.employee),
            "date": overtime.date,
            "hours": overtime.hours,
            "rate_category": overtime.rate_category,
            "state": overtime.state,
        }
        for overtime in overtimes
    ]


def absenteeism_by_department_rows(
    tenant: Tenant, *, year: int, month: int
) -> list[dict[str, Any]]:
    """PRS-ABSENT : taux d'absentéisme par département/atelier."""
    employees = PrsEmployee.objects.filter(tenant=tenant, is_active=True).select_related(
        "department"
    )
    rows_by_department: dict[str, dict[str, Any]] = {}
    for employee in employees:
        department_name = employee.department.name if employee.department else "—"
        entry = rows_by_department.setdefault(
            department_name, {"department": department_name, "employee_count": 0, "absence_days": 0}
        )
        entry["employee_count"] += 1

    absences = PrsAbsence.objects.filter(
        tenant=tenant,
        is_active=True,
        date_from__year=year,
        date_from__month=month,
        state__in=[PrsAbsence.STATE_VALIDATED, PrsAbsence.STATE_IN_PROGRESS, PrsAbsence.STATE_DONE],
    ).select_related("employee__department")
    for absence in absences:
        department_name = absence.employee.department.name if absence.employee.department else "—"
        entry = rows_by_department.setdefault(
            department_name, {"department": department_name, "employee_count": 0, "absence_days": 0}
        )
        entry["absence_days"] += float(absence.days_count)

    return list(rows_by_department.values())


def reconciliation_rows(tenant: Tenant, *, year: int, month: int) -> list[dict[str, Any]]:
    """PRS-COHER : écart présence/CRA (RG-PRS-8)."""
    employees = PrsEmployee.objects.filter(tenant=tenant, is_active=True)
    rows: list[dict[str, Any]] = []
    for employee in employees:
        report = reconcile_month(tenant, employee, year=year, month=month)
        rows.append(
            {
                "employee_name": str(employee),
                "presence_hours": report["presence_hours"],
                "cra_hours": report["cra_hours"],
                "deviation_pct": report["deviation_pct"],
                "flagged": report["flagged"],
            }
        )
    return rows
