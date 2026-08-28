"""RG-PRS-8 : rapprochement heures de presence / heures declarees en CRA
(MRP, deja construit). Ecart >10% sur un mois signale, SANS blocage — aide
au pilotage seulement, jamais un correctif automatique de l'un ou l'autre
cote."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db.models import Sum

from apps.mrp.services.public import get_employee_cra_hours
from apps.presence.models import PrsAttendance, PrsEmployee

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant

DEVIATION_THRESHOLD_PCT = Decimal("10")


def _month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    date_from = dt.date(year, month, 1)
    if month < 12:
        date_to = dt.date(year, month + 1, 1) - dt.timedelta(days=1)
    else:
        date_to = dt.date(year, 12, 31)
    return date_from, date_to


def monthly_presence_hours(employee: PrsEmployee, *, year: int, month: int) -> Decimal:
    date_from, date_to = _month_bounds(year, month)
    total = PrsAttendance.objects.filter(
        tenant=employee.tenant, employee=employee, date__gte=date_from, date__lte=date_to
    ).aggregate(total=Sum("worked_minutes"))["total"]
    minutes = total if total is not None else 0
    return (Decimal(minutes) / Decimal(60)).quantize(Decimal("0.01"))


def reconcile_month(
    tenant: Tenant, employee: PrsEmployee, *, year: int, month: int
) -> dict[str, object]:
    """Retourne un rapport de rapprochement (jamais une exception, jamais
    un blocage) : heures de presence, heures CRA, ecart en %, et un
    booleen `flagged` si l'ecart depasse `DEVIATION_THRESHOLD_PCT`."""
    date_from, date_to = _month_bounds(year, month)
    presence_hours = monthly_presence_hours(employee, year=year, month=month)
    cra_hours = Decimal(0)
    linked_user = employee.user
    if linked_user is not None:
        cra_hours = get_employee_cra_hours(
            tenant, linked_user, date_from=date_from, date_to=date_to
        )

    if presence_hours == 0:
        deviation_pct = Decimal(100) if cra_hours else Decimal(0)
    else:
        deviation_pct = abs(presence_hours - cra_hours) / presence_hours * Decimal(100)
    deviation_pct = deviation_pct.quantize(Decimal("0.01"))

    return {
        "employee_id": employee.id,
        "year": year,
        "month": month,
        "presence_hours": presence_hours,
        "cra_hours": cra_hours,
        "deviation_pct": deviation_pct,
        "flagged": deviation_pct > DEVIATION_THRESHOLD_PCT,
    }
