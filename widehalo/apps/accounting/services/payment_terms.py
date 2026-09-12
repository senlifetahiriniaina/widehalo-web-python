"""RG-ACC-6 : un echeancier genere autant de lignes d'echeance distinctes
que de lignes de conditions de paiement (ex. « 30% a la commande, 40% a
30 jours, 30% a 60 jours »)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.accounting.models import AccMove, AccPaymentTerm, AccPaymentTermLine


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


def _instalments(
    term: AccPaymentTerm | None, total: Decimal, base_date: dt.date
) -> list[tuple[Decimal, dt.date]]:
    """Les echeances de `total`, dont la DERNIERE absorbe l'arrondi.

    `generate_due_lines` quantifie chaque part a 0,0001 : trois parts de
    33,33 % ne redonnent pas exactement le total. Or `post_move` compare
    debit et credit A L'EGALITE STRICTE — une derive d'un dix-millieme
    suffirait a refuser la publication d'une facture parfaitement legitime.
    On force donc la derniere echeance au reliquat.
    """
    parts = generate_due_lines(term, total, base_date) if term is not None else [(total, base_date)]
    if not parts:
        return [(total, base_date)]
    montants = [montant for montant, _echeance in parts]
    reliquat = total - sum(montants[:-1], Decimal(0))
    parts[-1] = (reliquat, parts[-1][1])
    return parts


def apply_payment_term(move: AccMove) -> int:
    """RG-ACC-6 : pose l'echeance des lignes de creance et de dette de
    `move`, en les eclatant en autant de lignes que la condition de
    paiement en declare. Rend le nombre de lignes d'echeance produites.

    **Pourquoi cette fonction existe.** `generate_due_lines` calcule
    « 30 % a la commande, 40 % a 30 jours, 30 % a 60 jours » depuis
    l'origine du projet et n'a jamais eu d'appelant ; `AccMove` n'avait
    aucune clef vers `AccPaymentTerm` ; rien n'ecrivait
    `AccMoveLine.due_date`. Quatre fonctionnalites livrees filtrent
    pourtant sur `due_date__isnull=False` — la relance client, la balance
    agee, l'echeancier et la prevision de tresorerie — et etaient donc
    VIDES pour toute facture.

    **Le repli compte autant que le cas nominal.** Une piece sans
    condition de paiement recoit une echeance unique a sa propre date :
    elle est exigible tout de suite. Sans ce repli, seules les factures
    a conditions echelonnees apparaitraient dans les quatre ecrans, et
    l'exploitant conclurait que la relance ne marche pas.

    **Idempotente par construction** : elle ne traite que les lignes dont
    l'echeance n'est pas encore posee. Un second appel ne redecoupe rien —
    lecon de `record_analytic_lines`, qui doublait ses lignes au deuxieme
    passage.

    Appelee par `validate_invoice` AVANT `post_move` : une fois publiee,
    l'ecriture est immuable par declencheur base.
    """
    from apps.accounting.models import AccAccount, AccMove
    from apps.accounting.services.moves import add_line

    if move.state != AccMove.STATE_DRAFT:
        raise ValidationError(
            _("L'échéancier se pose sur un brouillon : l'écriture publiée est immuable.")
        )

    produites = 0
    lignes = list(
        move.lines.filter(
            account__type__in=(AccAccount.TYPE_RECEIVABLE, AccAccount.TYPE_PAYABLE),
            due_date__isnull=True,
        ).select_related("account")
    )
    for ligne in lignes:
        au_debit = ligne.debit > 0
        total = ligne.debit if au_debit else ligne.credit
        if total <= 0:
            continue
        parts = _instalments(move.payment_term, total, move.date)
        devise = ligne.amount_currency
        parts_devise: list[Decimal | None] = [None] * len(parts)
        if devise is not None and total > 0:
            cumul = Decimal(0)
            for rang, (montant, _echeance) in enumerate(parts):
                if rang < len(parts) - 1:
                    part = (devise * montant / total).quantize(Decimal("0.0001"))
                    cumul += part
                else:
                    part = devise - cumul
                parts_devise[rang] = part

        premier_montant, premiere_echeance = parts[0]
        if au_debit:
            ligne.debit = premier_montant
        else:
            ligne.credit = premier_montant
        ligne.due_date = premiere_echeance
        if devise is not None:
            ligne.amount_currency = parts_devise[0]
            ligne.save(update_fields=["debit", "credit", "due_date", "amount_currency"])
        else:
            ligne.save(update_fields=["debit", "credit", "due_date"])
        produites += 1

        for rang, (montant, echeance) in enumerate(parts[1:], start=1):
            add_line(
                move,
                account=ligne.account,
                label=ligne.label,
                debit=montant if au_debit else Decimal(0),
                credit=Decimal(0) if au_debit else montant,
                partner_id=ligne.partner_id,
                due_date=echeance,
                amount_currency=parts_devise[rang],
                currency=ligne.currency,
            )
            produites += 1

    return produites
