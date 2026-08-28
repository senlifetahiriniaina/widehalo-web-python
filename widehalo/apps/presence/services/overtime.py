"""PR2 : heures supplementaires classees par categorie de majoration
(RG-PRS-4)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING

from apps.core.services.workflow import attempt_transition
from apps.presence.models import PrsEmployee, PrsOvertime

if TYPE_CHECKING:
    from apps.core.models.user import User


def record_overtime(
    employee: PrsEmployee,
    *,
    date: dt.date,
    hours: Decimal,
    rate_category: str,
    payroll_period: str = "",
) -> PrsOvertime:
    overtime = PrsOvertime(
        tenant=employee.tenant,
        employee=employee,
        date=date,
        hours=hours,
        rate_category=rate_category,
        payroll_period=payroll_period,
    )
    overtime.full_clean()
    overtime.save()
    return overtime


def validate_overtime(overtime: PrsOvertime, user: User) -> PrsOvertime:
    attempt_transition(overtime, "validate", user)
    overtime.validated_by = user
    overtime.save(update_fields=["state", "validated_by"])
    return overtime
