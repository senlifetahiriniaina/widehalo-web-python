"""API django-ninja du module `presence` (§5.9.7). Expose les services
deja construits PR1-PR3 — aucune nouvelle logique metier ici, meme
discipline que `apps.logistics.api` (gabarit).

RG-PRS-9/test d'acceptance §5.9.8 n°4 : un `collaborateur` ne voit que ses
propres pointages/absences — `_scope_own_or_all` centralise ce filtrage
N3, applique explicitement dans chaque endpoint de liste concerne (RH/
admin/direction voient tout)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from apps.core.services.permissions import require_permission, user_role_codes
from apps.presence.models import (
    PrsAbsence,
    PrsAbsenceType,
    PrsAttendance,
    PrsEmployee,
    PrsLeaveBalance,
    PrsOvertime,
)
from apps.presence.services.absences import (
    cancel_absence,
    create_absence,
    decide_pending_absence_request,
    submit_absence,
)
from apps.presence.services.attendance import check_in, check_out
from apps.presence.services.employees import create_employee
from apps.presence.services.overtime import record_overtime

router = Router(tags=["presence"])

_STAFF_ROLES = {"rh", "admin", "direction"}


def _error_response(exc: Exception) -> JsonResponse:
    message = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
    return JsonResponse({"detail": message}, status=400)


def _can_see_all(request: Any) -> bool:
    return bool(user_role_codes(request.auth) & _STAFF_ROLES)


def _own_employee_id(request: Any) -> uuid.UUID | None:
    employee = PrsEmployee.objects.filter(user=request.auth, is_active=True).first()
    return employee.id if employee else None


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CheckInIn(Schema):
    employee_id: uuid.UUID
    mode: str
    location: str = PrsAttendance.LOCATION_SITE
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    site_latitude: Decimal | None = None
    site_longitude: Decimal | None = None
    radius_meters: int | None = None


class CheckOutIn(Schema):
    attendance_id: uuid.UUID
    latitude: Decimal | None = None
    longitude: Decimal | None = None


class EmployeeIn(Schema):
    first_name: str
    last_name: str
    hire_date: dt.date
    job_title: str = ""


class AbsenceIn(Schema):
    employee_id: uuid.UUID
    absence_type_id: uuid.UUID
    date_from: dt.date
    date_to: dt.date
    half_day_start: bool = False
    half_day_end: bool = False
    reason: str = ""


class AbsenceDecisionIn(Schema):
    comment: str = ""


class OvertimeIn(Schema):
    employee_id: uuid.UUID
    date: dt.date
    hours: Decimal
    rate_category: str


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def _serialize_employee(employee: PrsEmployee) -> dict[str, Any]:
    return {
        "id": str(employee.id),
        "reference": employee.reference,
        "first_name": employee.first_name,
        "last_name": employee.last_name,
        "hire_date": employee.hire_date.isoformat(),
        "job_title": employee.job_title,
        "department_id": str(employee.department_id) if employee.department_id else None,
    }


def _serialize_attendance(attendance: PrsAttendance) -> dict[str, Any]:
    return {
        "id": str(attendance.id),
        "employee_id": str(attendance.employee_id),
        "date": attendance.date.isoformat(),
        "check_in": attendance.check_in.isoformat() if attendance.check_in else None,
        "check_out": attendance.check_out.isoformat() if attendance.check_out else None,
        "mode": attendance.mode,
        "location": attendance.location,
        "within_perimeter": attendance.within_perimeter,
        "worked_minutes": attendance.worked_minutes,
        "late_minutes": attendance.late_minutes,
        "overtime_minutes": attendance.overtime_minutes,
        "state": attendance.state,
    }


def _serialize_absence(absence: PrsAbsence) -> dict[str, Any]:
    return {
        "id": str(absence.id),
        "reference": absence.reference,
        "employee_id": str(absence.employee_id),
        "type_id": str(absence.type_id),
        "date_from": absence.date_from.isoformat(),
        "date_to": absence.date_to.isoformat(),
        "days_count": absence.days_count,
        "state": absence.state,
    }


def _serialize_balance(balance: PrsLeaveBalance) -> dict[str, Any]:
    return {
        "id": str(balance.id),
        "employee_id": str(balance.employee_id),
        "year": balance.year,
        "type_id": str(balance.type_id),
        "acquired_days": balance.acquired_days,
        "taken_days": balance.taken_days,
        "pending_days": balance.pending_days,
        "remaining_days": balance.remaining_days,
    }


def _serialize_overtime(overtime: PrsOvertime) -> dict[str, Any]:
    return {
        "id": str(overtime.id),
        "employee_id": str(overtime.employee_id),
        "date": overtime.date.isoformat(),
        "hours": overtime.hours,
        "rate_category": overtime.rate_category,
        "state": overtime.state,
    }


# ---------------------------------------------------------------------------
# Pointage
# ---------------------------------------------------------------------------


@router.post("/presence/check-in")
@require_permission("presence.add_prsattendance")
def check_in_endpoint(request, payload: CheckInIn):
    employee = get_object_or_404(PrsEmployee, id=payload.employee_id)
    try:
        attendance = check_in(
            employee,
            mode=payload.mode,
            location=payload.location,
            latitude=payload.latitude,
            longitude=payload.longitude,
            site_latitude=payload.site_latitude,
            site_longitude=payload.site_longitude,
            radius_meters=payload.radius_meters,
        )
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_attendance(attendance)


@router.post("/presence/check-out")
@require_permission("presence.change_prsattendance")
def check_out_endpoint(request, payload: CheckOutIn):
    attendance = get_object_or_404(PrsAttendance, id=payload.attendance_id)
    try:
        attendance = check_out(attendance, latitude=payload.latitude, longitude=payload.longitude)
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_attendance(attendance)


@router.get("/presence/attendances")
@require_permission("presence.view_prsattendance")
def list_attendances(
    request,
    employee: uuid.UUID | None = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
):
    queryset = PrsAttendance.objects.filter(is_active=True)
    if not _can_see_all(request):
        own_id = _own_employee_id(request)
        queryset = queryset.filter(employee_id=own_id) if own_id else queryset.none()
    if employee is not None:
        queryset = queryset.filter(employee_id=employee)
    if date_from is not None:
        queryset = queryset.filter(date__gte=date_from)
    if date_to is not None:
        queryset = queryset.filter(date__lte=date_to)
    return {"results": [_serialize_attendance(a) for a in queryset.order_by("-date")[:200]]}


# ---------------------------------------------------------------------------
# Employes
# ---------------------------------------------------------------------------


@router.get("/presence/employees")
@require_permission("presence.view_prsemployee")
def list_employees(request):
    employees = PrsEmployee.objects.filter(is_active=True).order_by("last_name", "first_name")
    return {"results": [_serialize_employee(e) for e in employees]}


@router.post("/presence/employees")
@require_permission("presence.add_prsemployee")
def create_employee_endpoint(request, payload: EmployeeIn):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    try:
        employee = create_employee(
            tenant,
            first_name=payload.first_name,
            last_name=payload.last_name,
            hire_date=payload.hire_date,
            job_title=payload.job_title,
        )
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_employee(employee)


# ---------------------------------------------------------------------------
# Absences
# ---------------------------------------------------------------------------


@router.get("/presence/absences")
@require_permission("presence.view_prsabsence")
def list_absences(request, employee: uuid.UUID | None = None):
    queryset = PrsAbsence.objects.filter(is_active=True)
    if not _can_see_all(request):
        own_id = _own_employee_id(request)
        queryset = queryset.filter(employee_id=own_id) if own_id else queryset.none()
    if employee is not None:
        queryset = queryset.filter(employee_id=employee)
    return {"results": [_serialize_absence(a) for a in queryset.order_by("-date_from")[:200]]}


@router.post("/presence/absences")
@require_permission("presence.add_prsabsence")
def create_absence_endpoint(request, payload: AbsenceIn):
    employee = get_object_or_404(PrsEmployee, id=payload.employee_id)
    absence_type = get_object_or_404(PrsAbsenceType, id=payload.absence_type_id)
    try:
        absence = create_absence(
            employee.tenant,
            employee=employee,
            absence_type=absence_type,
            date_from=payload.date_from,
            date_to=payload.date_to,
            half_day_start=payload.half_day_start,
            half_day_end=payload.half_day_end,
            reason=payload.reason,
        )
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_absence(absence)


@router.post("/presence/absences/{absence_id}/submit")
@require_permission("presence.change_prsabsence")
def submit_absence_endpoint(request, absence_id: uuid.UUID):
    absence = get_object_or_404(PrsAbsence, id=absence_id)
    try:
        absence = submit_absence(absence, request.auth)
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_absence(absence)


@router.post("/presence/absences/{absence_id}/approve")
@require_permission("presence.change_prsabsence")
def approve_absence_endpoint(request, absence_id: uuid.UUID, payload: AbsenceDecisionIn):
    absence = get_object_or_404(PrsAbsence, id=absence_id)
    try:
        absence = decide_pending_absence_request(
            absence, request.auth, approved=True, comment=payload.comment
        )
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_absence(absence)


@router.post("/presence/absences/{absence_id}/reject")
@require_permission("presence.change_prsabsence")
def reject_absence_endpoint(request, absence_id: uuid.UUID, payload: AbsenceDecisionIn):
    absence = get_object_or_404(PrsAbsence, id=absence_id)
    try:
        absence = decide_pending_absence_request(
            absence, request.auth, approved=False, comment=payload.comment
        )
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_absence(absence)


@router.post("/presence/absences/{absence_id}/cancel")
@require_permission("presence.change_prsabsence")
def cancel_absence_endpoint(request, absence_id: uuid.UUID):
    absence = get_object_or_404(PrsAbsence, id=absence_id)
    try:
        absence = cancel_absence(absence, request.auth)
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_absence(absence)


# ---------------------------------------------------------------------------
# Soldes de conges
# ---------------------------------------------------------------------------


@router.get("/presence/balances")
@require_permission("presence.view_prsleavebalance")
def list_balances(request, employee: uuid.UUID | None = None, year: int | None = None):
    queryset = PrsLeaveBalance.objects.filter(is_active=True)
    if not _can_see_all(request):
        own_id = _own_employee_id(request)
        queryset = queryset.filter(employee_id=own_id) if own_id else queryset.none()
    if employee is not None:
        queryset = queryset.filter(employee_id=employee)
    if year is not None:
        queryset = queryset.filter(year=year)
    return {"results": [_serialize_balance(b) for b in queryset.order_by("-year")]}


# ---------------------------------------------------------------------------
# Calendrier d'equipe
# ---------------------------------------------------------------------------


@router.get("/presence/team-calendar")
@require_permission("presence.view_prsabsence")
def team_calendar(request, date: dt.date):
    absences = PrsAbsence.objects.filter(
        is_active=True,
        date_from__lte=date,
        date_to__gte=date,
        state__in=[PrsAbsence.STATE_VALIDATED, PrsAbsence.STATE_IN_PROGRESS],
    ).select_related("employee")
    attendances = PrsAttendance.objects.filter(is_active=True, date=date).select_related("employee")
    return {
        "date": date.isoformat(),
        "absent": [
            {"employee_id": str(a.employee_id), "type_id": str(a.type_id)} for a in absences
        ],
        "present": [{"employee_id": str(a.employee_id), "mode": a.mode} for a in attendances],
    }


# ---------------------------------------------------------------------------
# Heures supplementaires
# ---------------------------------------------------------------------------


@router.get("/presence/overtimes")
@require_permission("presence.view_prsovertime")
def list_overtimes(request, employee: uuid.UUID | None = None):
    queryset = PrsOvertime.objects.filter(is_active=True)
    if not _can_see_all(request):
        own_id = _own_employee_id(request)
        queryset = queryset.filter(employee_id=own_id) if own_id else queryset.none()
    if employee is not None:
        queryset = queryset.filter(employee_id=employee)
    return {"results": [_serialize_overtime(o) for o in queryset.order_by("-date")[:200]]}


@router.post("/presence/overtimes")
@require_permission("presence.add_prsovertime")
def create_overtime_endpoint(request, payload: OvertimeIn):
    employee = get_object_or_404(PrsEmployee, id=payload.employee_id)
    try:
        overtime = record_overtime(
            employee,
            date=payload.date,
            hours=payload.hours,
            rate_category=payload.rate_category,
        )
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_overtime(overtime)
