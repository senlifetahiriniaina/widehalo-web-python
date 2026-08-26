"""Cycle de vie d'une ecriture comptable : brouillon -> publication ->
(extourne). RG-ACC-1 (partie double), RG-ACC-3 (numerotation a la
publication) et RG-ACC-4 (periodes closes) sont verifies ici, en plus de la
garantie base (CHECK + trigger, cf. migration 0003)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils.translation import gettext as _

from apps.accounting.models import AccAccount, AccJournal, AccMove, AccMoveLine, AccPeriod, AccTax
from apps.core.models.tenant import Tenant
from apps.core.services.sequences import next_reference


def create_draft_move(
    *,
    tenant: Tenant,
    journal: AccJournal,
    period: AccPeriod,
    date: Any,
    move_type: str = AccMove.TYPE_ENTRY,
    partner_id: UUID | None = None,
    narration: str = "",
    currency: str = "MGA",
    exchange_rate: Decimal = Decimal(1),
) -> AccMove:
    return AccMove.objects.create(
        tenant=tenant,
        journal=journal,
        period=period,
        date=date,
        move_type=move_type,
        partner_id=partner_id,
        narration=narration,
        currency=currency,
        exchange_rate=exchange_rate,
        state=AccMove.STATE_DRAFT,
    )


def add_line(
    move: AccMove,
    *,
    account: AccAccount,
    label: str = "",
    debit: Decimal = Decimal(0),
    credit: Decimal = Decimal(0),
    partner_id: UUID | None = None,
    analytic_distribution: dict[str, Any] | None = None,
    due_date: Any = None,
    tax: AccTax | None = None,
    tax_base: Decimal | None = None,
) -> AccMoveLine:
    if move.state != AccMove.STATE_DRAFT:
        raise ValidationError(_("Impossible d'ajouter une ligne a une ecriture non brouillon."))
    return AccMoveLine.objects.create(
        tenant=move.tenant,
        move=move,
        account=account,
        label=label,
        debit=debit,
        credit=credit,
        partner_id=partner_id,
        analytic_distribution=analytic_distribution or {},
        due_date=due_date,
        tax=tax,
        tax_base=tax_base,
    )


def post_move(move: AccMove) -> AccMove:
    """RG-ACC-1 : refuse la publication si debit != credit. RG-ACC-3 : la
    reference n'est attribuee qu'ici, jamais au brouillon. RG-ACC-4 : refuse
    la publication dans une periode close."""
    if move.state != AccMove.STATE_DRAFT:
        raise ValidationError(_("Seule une ecriture en brouillon peut etre publiee."))
    if move.period.state == AccPeriod.STATE_CLOSED:
        raise ValidationError(_("Periode close : publication refusee."))

    totals = move.lines.aggregate(debit=Sum("debit"), credit=Sum("credit"))
    total_debit = totals["debit"] or Decimal(0)
    total_credit = totals["credit"] or Decimal(0)
    if total_debit != total_credit:
        raise ValidationError(
            _("Ecriture desequilibree : total debit (%(debit)s) != total credit (%(credit)s).")
            % {"debit": total_debit, "credit": total_credit}
        )

    with transaction.atomic():
        reference = next_reference(
            move.tenant, move.journal.sequence_prefix, move.period.fiscal_year.date_start.year
        )
        move.reference = reference
        move.total_debit = total_debit
        move.total_credit = total_credit
        move.state = AccMove.STATE_POSTED
        move.save(update_fields=["reference", "total_debit", "total_credit", "state"])

    return move


def reverse_move(move: AccMove, *, motif: str) -> AccMove:
    """Cree une nouvelle ecriture qui inverse debit/credit de `move` et la
    publie immediatement — `move` elle-meme n'est jamais modifiee (immuable,
    RG-ACC-2)."""
    if move.state != AccMove.STATE_POSTED:
        raise ValidationError(_("Seule une ecriture publiee peut etre extournee."))
    if not motif:
        raise ValidationError(_("Un motif est obligatoire pour extourner une ecriture."))

    reversal = create_draft_move(
        tenant=move.tenant,
        journal=move.journal,
        period=move.period,
        date=move.date,
        move_type=move.move_type,
        partner_id=move.partner_id,
        narration=_("Extourne de %(reference)s : %(motif)s")
        % {"reference": move.reference, "motif": motif},
        currency=move.currency,
        exchange_rate=move.exchange_rate,
    )
    reversal.reverses = move
    reversal.save(update_fields=["reverses"])

    for line in move.lines.all():
        add_line(
            reversal,
            account=line.account,
            label=line.label,
            debit=line.credit,
            credit=line.debit,
            partner_id=line.partner_id,
            analytic_distribution=line.analytic_distribution,
            due_date=line.due_date,
            tax=line.tax,
            tax_base=line.tax_base,
        )

    return post_move(reversal)
