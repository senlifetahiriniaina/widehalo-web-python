"""Calendrier ouvré — la règle du week-end, et rien d'autre en dur.

Déplacé depuis `apps/forecast/services/calendar.py` avec le modèle qu'il
lit (cf. `apps/core/models/calendar.py` pour le motif). Les deux fonctions
d'origine sont reprises à l'identique ; `next_business_day` et
`business_day_on_or_after` sont neuves — c'est ce dont la planification des
flux a besoin (axe A4) et que `is_business_day`/`business_days_in_month` ne
donnaient pas.

**AUCUNE date fériée n'est écrite ici**, et c'est vérifié par
`tests/architecture/test_no_hardcoded_holidays.py`. Seule la règle du
week-end (samedi/dimanche) est codée : un jour férié n'existe QUE via une
ligne `Holiday`, chargée par `manage.py load_mg_holidays` ou saisie à
l'écran.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from apps.core.models.calendar import Holiday

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant

#: Un calendrier peut être renseigné de travers — une société qui marquerait
#: par erreur une année entière comme fériée ferait tourner indéfiniment une
#: recherche de jour ouvré, dans un worker, sans jamais rien signaler. La
#: borne transforme une boucle infinie en erreur nommée. Une année et un jour
#: : au-delà, ce n'est plus un pont, c'est une saisie fausse.
MAX_LOOKAHEAD_DAYS = 366


class NoBusinessDayFoundError(Exception):
    """Aucun jour ouvré trouvé dans l'année qui suit la date de départ."""


def is_business_day(
    tenant: Tenant, date: dt.date, *, holiday_dates: set[dt.date] | None = None
) -> bool:
    if date.isoweekday() in (6, 7):
        return False
    if holiday_dates is not None:
        return date not in holiday_dates
    return not Holiday.objects.filter(tenant=tenant, date=date).exists()


def business_days_in_month(tenant: Tenant, year: int, month: int) -> int:
    holiday_dates = set(
        Holiday.objects.filter(tenant=tenant, date__year=year, date__month=month).values_list(
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


def business_day_on_or_after(tenant: Tenant, date: dt.date) -> dt.date:
    """`date` elle-même si elle est ouvrée, sinon le premier jour ouvré qui
    suit.

    C'est la fonction dont une PLANIFICATION a besoin : une échéance
    calculée qui tombe un dimanche doit glisser au lundi, mais une échéance
    qui tombe déjà un mardi ne doit pas glisser au mercredi. Distinguer les
    deux cas dans chaque appelant est exactement le genre de détail qu'on
    finit par oublier à un endroit sur trois."""
    holiday_dates = _holidays_in_window(tenant, date)
    cursor = date
    for _ in range(MAX_LOOKAHEAD_DAYS):
        if is_business_day(tenant, cursor, holiday_dates=holiday_dates):
            return cursor
        cursor += dt.timedelta(days=1)
    raise NoBusinessDayFoundError(
        f"Aucun jour ouvré entre le {date.isoformat()} et {MAX_LOOKAHEAD_DAYS} jours plus tard : "
        "le calendrier férié de cette société est vraisemblablement erroné."
    )


def next_business_day(tenant: Tenant, date: dt.date) -> dt.date:
    """Le premier jour ouvré STRICTEMENT après `date`, que `date` soit
    ouvrée ou non."""
    return business_day_on_or_after(tenant, date + dt.timedelta(days=1))


def _holidays_in_window(tenant: Tenant, start: dt.date) -> set[dt.date]:
    """Une seule requête pour toute la fenêtre de recherche, plutôt qu'un
    `exists()` par jour balayé. Un pont de quatre jours coûtait cinq
    allers-retours ; il en coûte un."""
    return set(
        Holiday.objects.filter(
            tenant=tenant,
            date__gte=start,
            date__lte=start + dt.timedelta(days=MAX_LOOKAHEAD_DAYS),
        ).values_list("date", flat=True)
    )
