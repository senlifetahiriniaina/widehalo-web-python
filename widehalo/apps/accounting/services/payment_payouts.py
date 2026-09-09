"""T5 (bloc D, PAY-5) — le versement groupé de l'agrégateur, et le lot
qu'il solde.

**Le critère, mot pour mot** : « le versement groupé de l'agrégateur est
rapproché du lot d'encaissements qu'il couvre, la commission étant isolée
sur son propre compte de charge ». Le cahier ajoute que c'est « la partie
du bloc D que l'on sous-estime systématiquement », et la mesure lui donne
raison : **aucun mécanisme 1 versement → N pièces n'existait**.
`AccPaymentAllocation` est structurellement N mais n'était jamais créé
qu'à un exemplaire, et `matching_number` n'était appliqué qu'à exactement
deux lignes.

**Ce qui rend le rapprochement possible, et qui a été posé avant lui.**
Une voie qui verse en lot (`PaymentProvider.settles_in_batch`) n'écrit pas
l'encaissement en banque : elle le porte au compte de PASSAGE. Le solde de
ce compte est, à tout instant, ce que l'agrégateur nous doit. Le versement
vient l'éteindre. Sans ce compte, il n'y aurait rien à solder — le
versement ne serait qu'un doublon à éviter, jamais un lot à lettrer.

**Une écriture, pas N.** Le patron est celui de
`create_pos_session_closing_entry_from_source`, le plus proche du dépôt :
un fait unique, une pièce consolidée. Débit banque du net réellement reçu,
débit du compte de commission, crédit du compte de passage pour le brut.
L'équilibre tient exactement quand net + commission = brut, ce que ce
module VÉRIFIE plutôt que de le supposer.

**Ce qui ne tombe pas juste ne s'écrit pas.** Un versement dont les
montants ne s'accordent pas avec le lot passe en `conteste` et ne produit
aucune écriture. C'est la même discipline que la notification orpheline de
PAY-3 — « ne produit aucune écriture tant qu'il n'est pas affecté » — et
c'est le seul comportement défendable : forcer l'équilibre en logeant la
différence dans un compte d'écart ferait disparaître, dans une écriture de
régularisation, précisément le fait qu'un agrégateur ne verse pas ce qu'il
doit.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.accounting.models import (
    AccAggregatorPayout,
    AccMove,
    AccMoveLine,
    AccPaymentNotification,
    AccTenantDefaultAccount,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from apps.core.models.tenant import Tenant

#: Ce qu'il est advenu d'un versement présenté au rapprochement.
OUTCOME_SETTLED = "rapproche"
OUTCOME_ALREADY_SETTLED = "deja_rapproche"
OUTCOME_NO_BATCH = "aucun_encaissement_a_couvrir"
OUTCOME_MISMATCH = "montants_discordants"


@dataclass(frozen=True)
class PayoutResult:
    """Ce qui a été fait, et de quoi l'expliquer à l'écran."""

    outcome: str
    payout: AccAggregatorPayout
    detail: str = ""

    @property
    def produced_an_entry(self) -> bool:
        """Vrai UNIQUEMENT quand la pièce consolidée existe. Un versement
        contesté, un lot vide ou un versement déjà rapproché n'écrivent
        rien — et aucun autre dénouement ne peut rendre cette propriété
        vraie."""
        return self.outcome == OUTCOME_SETTLED


def announce_payout(
    tenant: Tenant,
    *,
    provider_code: str,
    external_reference: str,
    payout_date: dt.date,
    gross_amount: Decimal,
    fee_amount: Decimal,
    net_amount: Decimal,
    currency: str = "MGA",
) -> AccAggregatorPayout:
    """Enregistre ce que l'agrégateur DIT qu'il verse.

    Séparé du rapprochement, parce que les deux n'arrivent ni au même
    moment ni par le même chemin : l'annonce vient d'un relevé
    d'agrégateur, le rapprochement d'une décision. Les fondre obligerait à
    tout avoir sous la main au même instant."""
    reference = (external_reference or "").strip()
    if not reference:
        raise ValidationError(
            _(
                "Un versement sans référence de l'agrégateur ne peut pas être "
                "dédoublonné : le même argent serait comptabilisé deux fois au "
                "prochain relevé."
            )
        )
    return AccAggregatorPayout.objects.create(
        tenant=tenant,
        provider_code=provider_code,
        external_reference=reference,
        payout_date=payout_date,
        gross_amount=Decimal(gross_amount),
        fee_amount=Decimal(fee_amount),
        net_amount=Decimal(net_amount),
        currency=currency,
    )


def settle_payout(
    payout: AccAggregatorPayout,
    *,
    notifications: Iterable[AccPaymentNotification] | None = None,
    now: dt.datetime | None = None,
) -> PayoutResult:
    """Rapproche le versement du lot qu'il couvre, et produit UNE écriture.

    `notifications` désigne le lot. Laissé vide, il est déduit : tous les
    encaissements rapprochés de cette voie qu'aucun versement ne couvre
    encore. C'est le cas courant — un agrégateur verse ce qu'il a encaissé
    depuis son dernier versement — et le laisser explicite reste possible
    pour le relevé qui nomme ses lignes.

    **Trois refus avant l'écriture, et chacun ferme un mode de faute
    différent** : un versement déjà rapproché (le même argent deux fois),
    un lot vide (une écriture qui ne solderait rien), des montants qui ne
    tombent pas juste (une écriture fausse, présentée comme vraie)."""
    tenant = payout.tenant
    maintenant_date = (now.date() if now else None) or payout.payout_date

    if payout.state == AccAggregatorPayout.STATE_SETTLED:
        return PayoutResult(outcome=OUTCOME_ALREADY_SETTLED, payout=payout)

    lot = list(
        notifications
        if notifications is not None
        else AccPaymentNotification.objects.filter(
            tenant=tenant,
            provider_code=payout.provider_code,
            state=AccPaymentNotification.STATE_MATCHED,
            payout__isnull=True,
        ).order_by("received_at")
    )
    if not lot:
        return PayoutResult(
            outcome=OUTCOME_NO_BATCH,
            payout=payout,
            detail=_("Aucun encaissement en attente de versement pour cette voie."),
        )

    brut_du_lot = sum((notification.amount for notification in lot), Decimal(0))
    ecarts = _mismatches(payout, brut_du_lot)
    if ecarts:
        payout.state = AccAggregatorPayout.STATE_DISPUTED
        payout.save(update_fields=["state"])
        return PayoutResult(outcome=OUTCOME_MISMATCH, payout=payout, detail=" ".join(ecarts))

    with transaction.atomic():
        piece = _post_consolidated_entry(payout, date=maintenant_date)
        numero = uuid.uuid4().hex[:12]
        _letter_the_batch(payout, lot, move=piece, matching_number=numero)

        payout.move = piece
        payout.matching_number = numero
        payout.state = AccAggregatorPayout.STATE_SETTLED
        payout.save(update_fields=["move", "matching_number", "state"])
        AccPaymentNotification.objects.filter(id__in=[n.id for n in lot]).update(payout=payout)

    return PayoutResult(outcome=OUTCOME_SETTLED, payout=payout)


def _mismatches(payout: AccAggregatorPayout, gross_of_batch: Decimal) -> list[str]:
    """Ce qui ne tombe pas juste, nommé plutôt que constaté.

    Deux accords indépendants, et les confondre reviendrait à ne rien
    vérifier : le versement doit être cohérent AVEC LUI-MÊME (net +
    commission = brut) et cohérent AVEC LE LOT (son brut = la somme des
    encaissements couverts). Un agrégateur peut parfaitement annoncer des
    montants qui s'additionnent et couvrir un autre lot que le nôtre."""
    ecarts: list[str] = []
    if payout.net_amount + payout.fee_amount != payout.gross_amount:
        ecarts.append(
            str(
                _(
                    "Le versement ne s'équilibre pas : %(net)s reçus + %(com)s de "
                    "commission ≠ %(brut)s annoncés."
                )
                % {
                    "net": payout.net_amount,
                    "com": payout.fee_amount,
                    "brut": payout.gross_amount,
                }
            )
        )
    if gross_of_batch != payout.gross_amount:
        ecarts.append(
            str(
                _(
                    "Le lot totalise %(lot)s, le versement annonce %(brut)s : il ne "
                    "couvre pas ces encaissements-là."
                )
                % {"lot": gross_of_batch, "brut": payout.gross_amount}
            )
        )
    return ecarts


def _post_consolidated_entry(payout: AccAggregatorPayout, *, date: dt.date) -> AccMove:
    """L'écriture unique : banque + commission au débit, passage au crédit."""
    from apps.accounting.models import AccJournal, AccPeriod
    from apps.accounting.services.default_accounts import resolve_default_account
    from apps.accounting.services.moves import add_line, create_draft_move, post_move

    tenant = payout.tenant
    periode = (
        AccPeriod.objects.filter(tenant=tenant, state=AccPeriod.STATE_OPEN)
        .order_by("date_start")
        .first()
    )
    if periode is None:
        raise ValidationError(_("Aucune période ouverte : le versement ne peut pas être écrit."))

    journal = (
        AccJournal.objects.filter(tenant=tenant, type=AccJournal.TYPE_BANK).order_by("code").first()
    )
    if journal is None:
        raise ValidationError(_("Aucun journal de banque configuré."))

    banque = resolve_default_account(tenant, AccTenantDefaultAccount.ROLE_BANK)
    passage = resolve_default_account(tenant, AccTenantDefaultAccount.ROLE_PAYMENT_CLEARING)
    commission = resolve_default_account(tenant, AccTenantDefaultAccount.ROLE_PAYMENT_FEE)
    manquants = [
        libelle
        for libelle, compte in (
            (_("banque"), banque),
            (_("passage d'encaissement"), passage),
            (_("commission d'encaissement"), commission),
        )
        if compte is None
    ]
    if banque is None or passage is None or commission is None:
        raise ValidationError(
            _(
                "Comptes par défaut manquants (%(liste)s) : le versement groupé "
                "ne peut pas être écrit."
            )
            % {"liste": ", ".join(str(libelle) for libelle in manquants)}
        )

    piece = create_draft_move(
        tenant=tenant,
        journal=journal,
        period=periode,
        date=date,
        narration=_("Versement groupé %(ref)s") % {"ref": payout.external_reference},
    )
    add_line(piece, account=banque, label=_("Versement reçu"), debit=payout.net_amount)
    if payout.fee_amount:
        add_line(
            piece,
            account=commission,
            label=_("Commission de l'agrégateur"),
            debit=payout.fee_amount,
        )
    add_line(
        piece,
        account=passage,
        label=_("Solde du compte de passage"),
        credit=payout.gross_amount,
    )
    return post_move(piece)


def _letter_the_batch(
    payout: AccAggregatorPayout,
    lot: list[AccPaymentNotification],
    *,
    move: AccMove,
    matching_number: str,
) -> None:
    """UN SEUL numéro de lettrage pour les N encaissements et le versement.

    **C'est là que « rapproché du lot » cesse d'être une figure de style.**
    Chaque encaissement a débité le compte de passage ; le versement le
    crédite en une fois. Leur donner le même numéro rend le rapprochement
    lisible dans le grand livre par une simple lecture du compte de
    passage : les lignes qui portent ce numéro s'annulent, celles qui n'en
    portent pas sont ce que l'agrégateur doit encore.

    Un numéro par pièce aurait produit N rapprochements de deux lignes,
    c'est-à-dire aucun rapprochement de lot — et le compte de passage
    resterait illisible, ce qui est exactement l'état d'avant."""
    passage_id = (
        AccTenantDefaultAccount.objects.filter(
            tenant=payout.tenant, role=AccTenantDefaultAccount.ROLE_PAYMENT_CLEARING
        )
        .values_list("account_id", flat=True)
        .first()
    )
    moves_du_lot = [
        notification.payment.move_id for notification in lot if notification.payment is not None
    ]
    AccMoveLine.objects.filter(
        tenant=payout.tenant, move_id__in=[*moves_du_lot, move.id], account_id=passage_id
    ).update(matching_number=matching_number)


__all__ = [
    "OUTCOME_ALREADY_SETTLED",
    "OUTCOME_MISMATCH",
    "OUTCOME_NO_BATCH",
    "OUTCOME_SETTLED",
    "PayoutResult",
    "announce_payout",
    "settle_payout",
]
