"""Facture client (§5.1.5) : une `AccMove` avec `move_type=customer_invoice`
— pas un modele separe. Le workflow metier (`invoice_state`) est distinct
du cycle de vie comptable (`state`, cf. services/moves.py) : la validation
d'une facture publie AUSSI l'ecriture sous-jacente (« validee (publiee) »
dans le diagramme du cahier des charges).

Validation a seuils (enrichissement WideHalo adopte, §5.1.14) : reutilise
`ApprovalRule`/`ApprovalRequest` du socle (Lot 1, etape 8) — sous 2M Ar,
validation directe ; de 2M a 10M Ar, double validation (2 approbateurs
sequentiels) ; au-dela, chaine complete (3 approbateurs)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from django.utils.translation import gettext as _

from apps.accounting.models import AccAccount, AccJournal, AccMove, AccPeriod
from apps.accounting.services.currency import get_rate
from apps.accounting.services.moves import add_line, create_draft_move, post_move
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.models.workflow import ApprovalRequest, ApprovalRule
from apps.core.services.approvals import request_approval
from apps.core.services.workflow import attempt_transition

DOUBLE_VALIDATION_THRESHOLD_MGA = Decimal("2000000")
FULL_CHAIN_THRESHOLD_MGA = Decimal("10000000")

RULE_NAME_LEVEL_1 = "accounting.invoice.validation.level1"
RULE_NAME_LEVEL_2 = "accounting.invoice.validation.level2"
RULE_NAME_LEVEL_3 = "accounting.invoice.validation.level3"


class ApprovalRequiredError(Exception):
    """La facture attend une ou plusieurs decisions d'approbation avant de
    pouvoir etre validee/publiee."""


def ensure_default_approval_thresholds(tenant: Tenant) -> None:
    """Cree, s'ils n'existent pas encore, les 3 paliers de validation par
    seuil suggeres par le cahier des charges — idempotent, et modifiable
    ensuite par le tenant (montants et roles parametrables)."""
    content_type = ContentType.objects.get_for_model(AccMove)
    defaults = [
        (RULE_NAME_LEVEL_1, "comptable", 1, DOUBLE_VALIDATION_THRESHOLD_MGA),
        (RULE_NAME_LEVEL_2, "resp_commercial", 2, DOUBLE_VALIDATION_THRESHOLD_MGA),
        (RULE_NAME_LEVEL_3, "direction", 3, FULL_CHAIN_THRESHOLD_MGA),
    ]
    for name, role, sequence_order, min_amount in defaults:
        ApprovalRule.objects.get_or_create(
            tenant=tenant,
            content_type=content_type,
            name=name,
            defaults={
                "approver_role": role,
                "sequence_order": sequence_order,
                "condition": {"min_amount": str(min_amount)},
            },
        )


def _applicable_rules(tenant: Tenant, amount: Decimal) -> QuerySet[ApprovalRule]:
    content_type = ContentType.objects.get_for_model(AccMove)
    rule_ids = [
        rule.id
        for rule in ApprovalRule.objects.filter(
            tenant=tenant, content_type=content_type, is_active=True
        ).order_by("sequence_order")
        if Decimal(rule.condition.get("min_amount", "0")) <= amount
    ]
    return ApprovalRule.objects.filter(id__in=rule_ids).order_by("sequence_order")


def create_invoice(
    *,
    tenant: Tenant,
    journal: AccJournal,
    period: AccPeriod,
    date: dt.date,
    partner_id: UUID | None,
    receivable_account: AccAccount,
    income_lines: list[dict[str, Any]],
    currency: str = "MGA",
) -> AccMove:
    """`income_lines` : liste de {"account": AccAccount, "amount": Decimal,
    "label": str}, montants exprimes dans `currency`. La ligne client
    (debit) est calculee automatiquement en somme des lignes de produit
    (credit). RG-ACC-7 : si `currency` differe de la devise de base du
    tenant, les lignes sont enregistrees converties en MGA au taux du jour
    de la facture (`amount_currency`/`currency` conservent le montant
    d'origine pour reference)."""
    total = sum((line["amount"] for line in income_lines), Decimal(0))
    is_foreign = currency != tenant.base_currency
    rate = get_rate(tenant, currency, date) if is_foreign else Decimal(1)

    def _mga(amount: Decimal) -> Decimal:
        return (amount * rate).quantize(Decimal("0.0001")) if is_foreign else amount

    move = create_draft_move(
        tenant=tenant,
        journal=journal,
        period=period,
        date=date,
        move_type=AccMove.TYPE_CUSTOMER_INVOICE,
        partner_id=partner_id,
        currency=currency,
        exchange_rate=rate,
    )
    add_line(
        move,
        account=receivable_account,
        label=_("Client"),
        debit=_mga(total),
        partner_id=partner_id,
        amount_currency=total if is_foreign else None,
        currency=currency,
    )
    for line in income_lines:
        add_line(
            move,
            account=line["account"],
            label=line.get("label", ""),
            credit=_mga(line["amount"]),
            amount_currency=line["amount"] if is_foreign else None,
            currency=currency,
        )

    return move


def validate_invoice(move: AccMove, user: User, *, comment: str = "") -> AccMove:
    """Verifie la chaine d'approbation requise par le montant de la
    facture ; si toutes les decisions necessaires sont approuvees (ou
    qu'aucune n'est requise sous le seuil), transitionne `invoice_state`
    et publie l'ecriture sous-jacente. Sinon, cree la prochaine demande
    d'approbation manquante et leve `ApprovalRequiredError`."""
    content_type = ContentType.objects.get_for_model(AccMove)
    rules = _applicable_rules(move.tenant, move.total_debit or _invoice_amount(move))

    for rule in rules:
        existing = ApprovalRequest.objects.filter(
            rule=rule, content_type=content_type, object_id=str(move.id)
        ).first()
        if existing is None:
            request_approval(move, rule, requested_by=user, comment=comment)
            raise ApprovalRequiredError(
                _("Validation en attente d'approbation (%(role)s).") % {"role": rule.approver_role}
            )
        if existing.status == ApprovalRequest.STATUS_PENDING:
            raise ApprovalRequiredError(
                _("Validation en attente d'approbation (%(role)s).") % {"role": rule.approver_role}
            )
        if existing.status == ApprovalRequest.STATUS_REJECTED:
            raise ValidationError(
                _("Validation rejetee par %(role)s.") % {"role": rule.approver_role}
            )

    if move.invoice_state == AccMove.INVOICE_STATE_DRAFT:
        move.submit_for_validation()
        move.save(update_fields=["invoice_state"])

    attempt_transition(move, "validate", user, comment=comment)
    move.save(update_fields=["invoice_state"])

    return post_move(move)


def cancel_invoice(move: AccMove, user: User, *, motif: str) -> AccMove:
    """Comptable uniquement, avant tout paiement — une facture deja
    publiee (RG-ACC-2, immuable) ne peut pas etre annulee directement : il
    faut passer par un avoir (extourne), pas par cette fonction."""
    if not motif:
        raise ValidationError(_("Un motif est obligatoire pour annuler une facture."))
    if move.state == AccMove.STATE_POSTED:
        raise ValidationError(
            _("Facture deja publiee : utiliser une extourne (avoir), pas une annulation directe.")
        )

    attempt_transition(move, "cancel", user, comment=motif)
    move.save(update_fields=["invoice_state"])
    return move


def _invoice_amount(move: AccMove) -> Decimal:
    receivable_line = move.lines.filter(debit__gt=0).order_by("-debit").first()
    return receivable_line.debit if receivable_line else Decimal(0)
