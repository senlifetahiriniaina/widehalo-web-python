"""Calendrier de référence (FOR-5 : « applique jours ouvrés/fériés
malgaches lus en table de référence ; un test vérifie qu'aucune date
fériée n'est écrite dans le code »). AUCUNE date n'est codée en dur ici —
seule la règle week-end (samedi/dimanche) l'est, un jour férié n'existe
QUE via une ligne `ForHoliday` créée par un utilisateur/une commande de
chargement (cf. `management/commands/load_mg_holidays.py`)."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from apps.forecast.models import ForHoliday

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant


def is_business_day(
    tenant: Tenant, date: dt.date, *, holiday_dates: set[dt.date] | None = None
) -> bool:
    if date.isoweekday() in (6, 7):
        return False
    if holiday_dates is not None:
        return date not in holiday_dates
    return not ForHoliday.objects.filter(tenant=tenant, date=date).exists()


def business_days_in_month(tenant: Tenant, year: int, month: int) -> int:
    holiday_dates = set(
        ForHoliday.objects.filter(tenant=tenant, date__year=year, date__month=month).values_list(
            "date", flat=True
        )
    )
    first = dt.date(year, month, 1)
    next_month = dt.date(year + 1, 1, 1) if month == 12 else dt.date(year, month + 1, 1)
    count = 0
    cursor = first
    while cursor < next_month:
        if is_business_day(tenant, cursor, holiday_dates=holiday_dates):
            count += 1
        cursor += dt.timedelta(days=1)
    return count
