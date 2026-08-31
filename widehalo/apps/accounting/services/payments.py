"""Enregistrement d'un paiement et lettrage (RG-ACC-8, lettrage partiel
autorise) contre une facture publiee. RG-ACC-7 : si le paiement est recu
dans la devise d'origine de la facture a un taux different de celui de la
facture, l'ecart de change est constate immediatement (comptabilise en
gain ou perte de change), jamais laisse en suspens."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils.translation import gettext as _

from apps.accounting.models import (
    AccAccount,
    AccJournal,
    AccMove,
    AccMoveLine,
    AccPayment,
    AccPaymentAllocation,
    AccPeriod,
)
from apps.accounting.services.currency import convert_to_mga
from apps.accounting.services.moves import add_line, create_draft_move, post_move


def _receivable_line(invoice: AccMove) -> AccMoveLine:
    line = invoice.lines.filter(debit__gt=0).order_by("-debit").first()
    if line is None:
        raise ValidationError(_("Cette écriture n'a pas de ligne créance a lettrer."))
    return line


def allocated_amount(move_line: AccMoveLine) -> Decimal:
    total = move_line.allocations.aggregate(total=Sum("amount"))["total"]
    return total or Decimal(0)


def outstanding_balance(move_line: AccMoveLine) -> Decimal:
    return move_line.debit - allocated_amount(move_line)


def register_payment(
    *,
    invoice: AccMove,
    period: AccPeriod,
    journal: AccJournal,
    cash_account: AccAccount,
    gain_account: AccAccount,
    loss_account: AccAccount,
    date: dt.date,
    amount: Decimal,
    method: str,
    reference_external: str = "",
) -> AccPayment:
    """`amount` est exprime dans la devise d'origine de la facture
    (`invoice.currency`) — pour une facture MGA (cas courant), c'est un
    montant MGA simple, sans conversion."""
    if invoice.state != AccMove.STATE_POSTED or invoice.move_type != AccMove.TYPE_CUSTOMER_INVOICE:
        raise ValidationError(_("Seule une facture client publiée peut recevoir un paiement."))

    receivable_line = _receivable_line(invoice)
    total_currency_due = receivable_line.amount_currency or receivable_line.debit
    if amount <= 0:
        raise ValidationError(_("Le montant du paiement doit être positif."))

    amount_mga = convert_to_mga(amount, invoice.currency, date, tenant=invoice.tenant)
    proportion = amount / total_currency_due
    attributed_mga = (receivable_line.debit * proportion).quantize(Decimal("0.0001"))
    exchange_difference = amount_mga - attributed_mga

    payment_move = create_draft_move(
        tenant=invoice.tenant,
        journal=journal,
        period=period,
        date=date,
        move_type=AccMove.TYPE_ENTRY,
        partner_id=invoice.partner_id,
        narration=_("Paiement facture %(reference)s") % {"reference": invoice.reference},
    )
    add_line(payment_move, account=cash_account, label=_("Encaissement"), debit=amount_mga)
    add_line(
        payment_move, account=receivable_line.account, label=_("Lettrage"), credit=attributed_mga
    )
    if exchange_difference > 0:
        add_line(
            payment_move,
            account=gain_account,
            label=_("Gain de change"),
            credit=exchange_difference,
        )
    elif exchange_difference < 0:
        add_line(
            payment_move,
            account=loss_account,
            label=_("Perte de change"),
            debit=-exchange_difference,
        )
    post_move(payment_move)

    payment = AccPayment.objects.create(
        tenant=invoice.tenant,
        partner_id=invoice.partner_id,
        journal=journal,
        date=date,
        amount=amount_mga,
        currency=invoice.tenant.base_currency,
        direction=AccPayment.DIRECTION_INBOUND,
        method=method,
        reference_external=reference_external,
        state=AccPayment.STATE_POSTED,
        move=payment_move,
    )

    matching_number = uuid.uuid4().hex[:12]
    AccPaymentAllocation.objects.create(
        tenant=invoice.tenant, payment=payment, move_line=receivable_line, amount=attributed_mga
    )
    payment_receivable_line = payment_move.lines.get(account=receivable_line.account)
    receivable_line.matching_number = matching_number
    receivable_line.reconciled_with = payment_receivable_line
    receivable_line.save(update_fields=["matching_number", "reconciled_with"])
    payment_receivable_line.matching_number = matching_number
    payment_receivable_line.save(update_fields=["matching_number"])

    remaining = outstanding_balance(receivable_line)
    if remaining <= 0:
        invoice.mark_paid()
    else:
        invoice.mark_paid_partially()
    invoice.save(update_fields=["invoice_state"])

    return payment
