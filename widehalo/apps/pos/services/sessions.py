"""Session de caisse (cahier §13.5) — ouverture, mouvements d'espèces,
calcul de l'encours attendu, clôture avec écart et écriture consolidée
(POS-6/POS-7)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounting.services.public import create_pos_session_closing_entry_from_source
from apps.pos.models import (
    PosCashMovement,
    PosOrder,
    PosOrderLine,
    PosPayment,
    PosPaymentMethod,
    PosRegister,
    PosSession,
)
from apps.pos.services.scoping import assert_can_manage_session

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User


def open_session(
    tenant: Tenant,
    *,
    register: PosRegister,
    cashier: User,
    opening_cash_amount: Decimal = Decimal(0),
    opened_at: dt.datetime | None = None,
) -> PosSession:
    """POS-2 : une vente n'est possible qu'en session `OPEN` — refuse
    (`ValidationError` i18n) d'ouvrir une SECONDE session sur un registre
    qui en a déjà une active (une caisse physique n'a qu'un seul état à un
    instant donné)."""
    if PosSession.objects.filter(register=register, state=PosSession.STATE_OPEN).exists():
        raise ValidationError(_("Ce point de caisse a déjà une session ouverte."))
    return PosSession.objects.create(
        tenant=tenant,
        register=register,
        cashier=cashier,
        opening_cash_amount=opening_cash_amount,
        opened_at=opened_at or timezone.now(),
        created_by=cashier,
    )


def add_cash_movement(
    session: PosSession, *, direction: str, amount: Decimal, reason: str, user: User | None = None
) -> PosCashMovement:
    """Mouvement d'espèces entrant/sortant MOTIVÉ (cahier, écran "Session
    de caisse") — refusé hors session ouverte, refusé sans motif (`reason`
    vide). Scope N3 (docs/RBAC.md §5) : `user` doit être le titulaire de
    la session, ou admin/direction/superutilisateur."""
    if user is not None:
        assert_can_manage_session(session, user)
    if session.state != PosSession.STATE_OPEN:
        raise ValidationError(_("Impossible d'enregistrer un mouvement sur une session clôturée."))
    if not reason.strip():
        raise ValidationError(_("Un mouvement d'espèces doit être motivé."))
    if amount <= 0:
        raise ValidationError(_("Le montant d'un mouvement d'espèces doit être positif."))
    return PosCashMovement.objects.create(
        tenant=session.tenant,
        session=session,
        direction=direction,
        amount=amount,
        reason=reason,
        created_by=user,
    )


def _cash_payment_method_ids(session: PosSession) -> set:
    return set(
        PosPaymentMethod.objects.filter(
            tenant=session.tenant, type=PosPaymentMethod.TYPE_CASH
        ).values_list("id", flat=True)
    )


def compute_expected_cash(session: PosSession) -> Decimal:
    """Encours espèces THÉORIQUE attendu au comptage (avant clôture) :
    fond de caisse d'ouverture + règlements espèces des ventes validées -
    règlements espèces des retours/avoirs validés + mouvements d'espèces
    entrants - sortants. N'inclut JAMAIS un moyen de paiement non-espèces
    (mobile money/carte/chèque ne se "comptent" pas physiquement — cahier,
    persona Caissier : "savoir immédiatement combien rendre... clôturer sa
    caisse sans discussion sur l'écart" ne porte que sur les espèces)."""
    cash_method_ids = _cash_payment_method_ids(session)
    if not cash_method_ids:
        cash_sales = Decimal(0)
        cash_returns = Decimal(0)
    else:
        cash_sales = PosPayment.objects.filter(
            order__session=session,
            order__state=PosOrder.STATE_VALIDATED,
            order__order_type=PosOrder.TYPE_SALE,
            method_id__in=cash_method_ids,
        ).aggregate(total=Sum("amount"))["total"] or Decimal(0)
        cash_returns = PosPayment.objects.filter(
            order__session=session,
            order__state=PosOrder.STATE_VALIDATED,
            order__order_type=PosOrder.TYPE_RETURN,
            method_id__in=cash_method_ids,
        ).aggregate(total=Sum("amount"))["total"] or Decimal(0)
    movements_in = PosCashMovement.objects.filter(
        session=session, direction=PosCashMovement.DIRECTION_IN
    ).aggregate(total=Sum("amount"))["total"] or Decimal(0)
    movements_out = PosCashMovement.objects.filter(
        session=session, direction=PosCashMovement.DIRECTION_OUT
    ).aggregate(total=Sum("amount"))["total"] or Decimal(0)
    return session.opening_cash_amount + cash_sales - cash_returns + movements_in - movements_out


def _net_payment_totals(session: PosSession) -> list[dict]:
    """Un montant PAR MOYEN DE PAIEMENT, net ventes - retours (le moyen
    espèces sera remplacé par le montant COMPTÉ par l'appelant, cf.
    `close_session` — cette fonction retourne le théorique pour tous les
    autres moyens)."""
    sale_totals = dict(
        PosPayment.objects.filter(
            order__session=session,
            order__state=PosOrder.STATE_VALIDATED,
            order__order_type=PosOrder.TYPE_SALE,
        )
        .values_list("method_id")
        .annotate(total=Sum("amount"))
    )
    return_totals = dict(
        PosPayment.objects.filter(
            order__session=session,
            order__state=PosOrder.STATE_VALIDATED,
            order__order_type=PosOrder.TYPE_RETURN,
        )
        .values_list("method_id")
        .annotate(total=Sum("amount"))
    )
    method_ids = set(sale_totals) | set(return_totals)
    methods = {m.id: m for m in PosPaymentMethod.objects.filter(id__in=method_ids)}
    totals = []
    for method_id in method_ids:
        method = methods[method_id]
        net = (sale_totals.get(method_id, Decimal(0))) - (return_totals.get(method_id, Decimal(0)))
        totals.append(
            {
                "method": method,
                "amount": net,
            }
        )
    return totals


def _net_sales_amounts(session: PosSession) -> tuple[Decimal, Decimal]:
    """`(amount_untaxed, amount_tax)` net ventes - retours, sur les
    commandes VALIDÉES de la session."""
    sale_agg = PosOrderLine.objects.filter(
        order__session=session,
        order__state=PosOrder.STATE_VALIDATED,
        order__order_type=PosOrder.TYPE_SALE,
    ).aggregate(untaxed=Sum("subtotal"), tax=Sum("tax_amount"))
    return_agg = PosOrderLine.objects.filter(
        order__session=session,
        order__state=PosOrder.STATE_VALIDATED,
        order__order_type=PosOrder.TYPE_RETURN,
    ).aggregate(untaxed=Sum("subtotal"), tax=Sum("tax_amount"))
    untaxed = (sale_agg["untaxed"] or Decimal(0)) - (return_agg["untaxed"] or Decimal(0))
    tax = (sale_agg["tax"] or Decimal(0)) - (return_agg["tax"] or Decimal(0))
    return untaxed, tax


@transaction.atomic
def close_session(
    session: PosSession,
    *,
    counted_cash: Decimal,
    variance_reason: str = "",
    user: User | None = None,
    date: dt.date | None = None,
) -> PosSession:
    """POS-6/POS-7/POS-9 : impose un comptage (`counted_cash`), calcule
    l'écart vs le théorique (`compute_expected_cash`), génère l'écriture
    comptable consolidée par moyen de paiement, puis clôture la session —
    IMMUABLE ensuite (POS-9, vérifié par `services.orders` qui refuse
    toute mutation sur une session dont `state != OPEN`).

    Un écart non nul EXIGE un motif (`variance_reason`) — jamais absorbé
    silencieusement (cahier : "tout écart de caisse est enregistré, motivé
    et journalisé"). Scope N3 (docs/RBAC.md §5) : `user` doit être le
    titulaire de la session, ou admin/direction/superutilisateur."""
    if user is not None:
        assert_can_manage_session(session, user)
    if session.state != PosSession.STATE_OPEN:
        raise ValidationError(_("Cette session est déjà clôturée."))

    close_date = date or timezone.now().date()
    expected_cash = compute_expected_cash(session)
    variance = counted_cash - expected_cash
    if variance != 0 and not variance_reason.strip():
        raise ValidationError(_("Un écart de caisse non nul doit être motivé avant la clôture."))

    cash_method_ids = _cash_payment_method_ids(session)
    payment_totals = _net_payment_totals(session)
    # Le compte caisse est TOUJOURS porté par le montant COMPTÉ
    # physiquement (`counted_cash`), jamais par le théorique — c'est ce qui
    # fait exister l'écart comme un déséquilibre structurel de l'écriture,
    # absorbé par la ligne d'écart de `create_pos_session_closing_entry_
    # from_source` (cf. sa docstring). **Simplification assumée** : un
    # SEUL comptage physique par session (`counted_cash`), donc un SEUL
    # moyen de paiement de type `cash` réellement représenté ici — s'il en
    # existe plusieurs pour ce tenant (cas rare, non prévu par le cahier
    # qui parle d'"espèces" au singulier), seul le premier est utilisé
    # pour résoudre le compte comptable, `counted_cash` restant le SEUL
    # montant compté qui compte.
    payment_totals_input = [
        {
            "account_id": entry["method"].account_id,
            "default_account_type": entry["method"].default_account_type,
            "amount": entry["amount"],
        }
        for entry in payment_totals
        if entry["method"].id not in cash_method_ids and entry["amount"]
    ]
    # Le fond de caisse d'ouverture ET les mouvements d'espèces manuels ne
    # sont jamais visibles dans `PosPayment` (aucune vente ne les porte) —
    # `counted_cash` (comptage physique réel) est donc TOUJOURS porté
    # intégralement au débit du compte caisse, même sur une session sans
    # aucune vente en espèces (ex. fond de caisse seul, ou uniquement des
    # ventes non-espèces).
    if cash_method_ids and counted_cash:
        cash_method = (
            PosPaymentMethod.objects.filter(id__in=cash_method_ids, is_active=True).first()
            or PosPaymentMethod.objects.filter(id__in=cash_method_ids).first()
        )
        if cash_method is not None:
            payment_totals_input.append(
                {
                    "account_id": cash_method.account_id,
                    "default_account_type": cash_method.default_account_type,
                    "amount": counted_cash,
                }
            )

    income_amount, tax_amount = _net_sales_amounts(session)

    closing_move_id = create_pos_session_closing_entry_from_source(
        tenant=session.tenant,
        date=close_date,
        payment_totals=payment_totals_input,
        income_amount_mga=income_amount,
        tax_amount_mga=tax_amount,
        cash_variance_mga=variance,
        label=_("Clôture caisse %(register)s — session du %(date)s")
        % {"register": session.register.code, "date": session.opened_at.date()},
    )

    session.closing_cash_counted = counted_cash
    session.closing_cash_expected = expected_cash
    session.cash_variance = variance
    session.cash_variance_reason = variance_reason
    session.closing_move_id = closing_move_id
    session.state = PosSession.STATE_CLOSED
    session.closed_at = timezone.now()
    session.updated_by = user
    session.save(
        update_fields=[
            "closing_cash_counted",
            "closing_cash_expected",
            "cash_variance",
            "cash_variance_reason",
            "closing_move_id",
            "state",
            "closed_at",
            "updated_by",
        ]
    )
    return session
