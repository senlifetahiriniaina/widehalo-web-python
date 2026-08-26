"""RG-ACC-6 : un echeancier genere autant de lignes d'echeance distinctes
que de lignes de conditions de paiement (ex. « 30% a la commande, 40% a
30 jours, 30% a 60 jours »)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from apps.accounting.models import AccPaymentTerm, AccPaymentTermLine


def _due_date(base_date: dt.date, line: AccPaymentTermLine) -> dt.date:
    due = base_date + relativedelta(months=line.month_offset, days=line.days)
    if line.day_of_month:
        due = due.replace(day=1) + relativedelta(day=line.day_of_month)
    return due


def generate_due_lines(
    term: AccPaymentTerm, total: Decimal, base_date: dt.date
) -> list[tuple[Decimal, dt.date]]:
    lines = list(term.lines.order_by("sequence"))
    if not lines:
        return [(total, base_date)]

    due_lines: list[tuple[Decimal, dt.date]] = []
    allocated = Decimal(0)

    for line in lines:
        if line.value_type == AccPaymentTermLine.VALUE_TYPE_PERCENT:
            amount = (total * (line.value or Decimal(0)) / Decimal(100)).quantize(Decimal("0.0001"))
        elif line.value_type == AccPaymentTermLine.VALUE_TYPE_FIXED:
            amount = line.value or Decimal(0)
        else:  # balance
            amount = total - allocated

        allocated += amount
        due_lines.append((amount, _due_date(base_date, line)))

    return due_lines
