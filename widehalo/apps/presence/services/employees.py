"""PR1 : employes, departements, calendriers de travail."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.core.services.sequences import next_reference
from apps.presence.models import PrsDepartment, PrsEmployee, PrsWorkCalendar

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User

EMPLOYEE_SEQUENCE_CODE = "PRS"


def create_department(
    tenant: Tenant,
    *,
    code: str,
    name: str,
    parent: PrsDepartment | None = None,
    manager: User | None = None,
) -> PrsDepartment:
    department = PrsDepartment(tenant=tenant, code=code, name=name, parent=parent, manager=manager)
    department.full_clean()
    department.save()
    return department


def create_work_calendar(
    tenant: Tenant,
    *,
    name: str,
    hours_per_week: Decimal = Decimal("40"),
    days: dict[str, list[list[str]]] | None = None,
    tolerance_min: int = 5,
    overtime_rules: dict[str, dict[str, str]] | None = None,
) -> PrsWorkCalendar:
    calendar = PrsWorkCalendar(
        tenant=tenant,
        name=name,
        hours_per_week=hours_per_week,
        days=days or {},
        tolerance_min=tolerance_min,
        overtime_rules=overtime_rules or {},
    )
    calendar.full_clean()
    calendar.save()
    return calendar


def create_employee(
    tenant: Tenant,
    *,
    first_name: str,
    last_name: str,
    hire_date: dt.date,
    user: User | None = None,
    birth_date: dt.date | None = None,
    gender: str = "",
    cin: str = "",
    cnaps_number: str = "",
    ostie_number: str = "",
    address: str = "",
    phone: str = "",
    emergency_contact: str = "",
    department: PrsDepartment | None = None,
    job_title: str = "",
    manager: PrsEmployee | None = None,
    workshop_id: UUID | None = None,
    work_calendar: PrsWorkCalendar | None = None,
) -> PrsEmployee:
    fiscal_year = hire_date.year
    employee = PrsEmployee(
        tenant=tenant,
        reference=next_reference(tenant, EMPLOYEE_SEQUENCE_CODE, fiscal_year),
        user=user,
        first_name=first_name,
        last_name=last_name,
        birth_date=birth_date,
        gender=gender,
        cin=cin,
        cnaps_number=cnaps_number,
        ostie_number=ostie_number,
        address=address,
        phone=phone,
        emergency_contact=emergency_contact,
        hire_date=hire_date,
        department=department,
        job_title=job_title,
        manager=manager,
        workshop_id=workshop_id,
        work_calendar=work_calendar,
    )
    employee.full_clean()
    employee.save()
    return employee


def terminate_employee(employee: PrsEmployee, *, end_date: dt.date) -> PrsEmployee:
    if end_date < employee.hire_date:
        raise ValidationError(_("La date de fin ne peut pas précéder la date d'embauche."))
    employee.end_date = end_date
    employee.full_clean()
    employee.save(update_fields=["end_date"])
    return employee
