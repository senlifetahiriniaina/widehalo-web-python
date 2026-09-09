"""T5 (bloc D, PAY-2 à PAY-4, PAY-6) — la notification qui produit une
écriture, et celle qui n'en produit pas.

**LA LIGNE DE PARTAGE, ET ELLE EST TOUT LE LOT.** Deux passages du cahier
paraissent se contredire, et une lecture attentive montre qu'ils ne
parlent pas de la même chose.

L'interdit (l.385) : « aucune automatisation ne crée ou ne modifie une
pièce comptable. Un flux entrant propose, un humain **ou une règle métier
déjà éprouvée** dispose. **Un relevé bancaire ingéré** produit des
propositions de lettrage, pas des écritures. »

PAY-2 : « une notification de paiement reçue est rapprochée automatiquement
de la pièce d'origine **dans le cas nominal**, et produit l'écriture
d'encaissement **sans intervention comptable**. »

L'interdit nomme lui-même son exception — « une règle métier déjà
éprouvée » — et donne son exemple : le RELEVÉ BANCAIRE, rapproché par
similarité. Il vise le rapprochement heuristique. PAY-2 parle d'un
ÉVÉNEMENT AUTHENTIFIÉ porteur d'une référence que nous avons nous-mêmes
émise : la corrélation n'y est pas une devinette, c'est une clef.

Et PAY-3 confirme la frontière en la nommant : « un paiement reçu **sans
correspondance** est placé en attente de rapprochement […] et ne produit
aucune écriture tant qu'il n'est pas affecté ».

**La règle qui en découle, et que `tests/architecture` vérifie** :
l'écriture automatique n'existe QUE sur corrélation réussie d'une
notification portant une référence d'intention émise par nous. Corrélation
échouée, montant qui ne tombe pas juste, ligne de relevé, similarité :
proposition, jamais écriture.

**Pourquoi ce module ne fait pas de correspondance approximative du
tout.** Ce serait la pente naturelle — « le montant et la date
correspondent, c'est sûrement ce paiement-là ». C'est exactement ce que
l'interdit vise, et le moteur qui a le droit de le faire existe déjà :
`bank_reconciliation.suggest_matches`, qui PROPOSE et ne poste rien. Y
ajouter une seconde heuristique ici, mais qui poste, viderait l'interdit
de son sens.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

if TYPE_CHECKING:
    from apps.accounting.models import (
        AccAccount,
        AccJournal,
        AccMove,
        AccPayment,
        AccPaymentIntent,
        AccPeriod,
    )
    from apps.core.models.tenant import Tenant

#: Ce qui est advenu d'une notification. Nommé plutôt que déduit d'un
#: booléen : « rapprochée », « orpheline » et « doublon » appellent trois
#: écrans différents et trois actions différentes, et un total qui les
#: additionnerait ne dirait rien à personne.
OUTCOME_SETTLED = "encaissee"
OUTCOME_ORPHAN = "orpheline"
OUTCOME_DUPLICATE = "doublon"
OUTCOME_NO_INTENT = "sans_intention"


@dataclass(frozen=True)
class SettlementResult:
    """Ce qu'il est advenu, et de quoi le présenter."""

    outcome: str
    notification_id: object = None
    payment_id: object = None

    @property
    def produced_an_entry(self) -> bool:
        """Vrai UNIQUEMENT sur corrélation réussie.

        C'est la propriété que la garde d'architecture interroge : aucune
        autre valeur d'`outcome` ne peut la rendre vraie."""
        return self.outcome == OUTCOME_SETTLED


def receive_payment_notification(
    tenant: Tenant,
    *,
    provider_code: str,
    external_reference: str,
    amount: Decimal,
    currency: str = "MGA",
    fee_amount: Decimal = Decimal(0),
    raw: str = "",
    now: dt.datetime | None = None,
) -> SettlementResult:
    """Enregistre la notification, et n'écrit une pièce que si elle corrèle.

    **Tout ce qui arrive laisse une ligne**, y compris ce qui ne corrèle
    pas et y compris un doublon : c'est le troisième interdit du §4.3
    (« aucune automatisation ne s'exécute sans laisser une ligne dans le
    registre […] y compris lorsqu'elle échoue »). Un doublon est marqué,
    jamais silencieusement jeté — le jeter ferait disparaître la preuve
    qu'il est arrivé deux fois."""
    from apps.accounting.models import AccPaymentIntent, AccPaymentNotification

    reference = (external_reference or "").strip()
    if not reference:
        # Sans référence, aucune corrélation n'est possible et aucune
        # heuristique ne la remplacera : la notification est enregistrée
        # orpheline pour que quelqu'un la voie.
        notification = AccPaymentNotification.objects.create(
            tenant=tenant,
            provider_code=provider_code,
            external_reference="",
            amount=amount,
            currency=currency,
            fee_amount=fee_amount,
            state=AccPaymentNotification.STATE_ORPHAN,
            raw=raw,
        )
        return SettlementResult(outcome=OUTCOME_ORPHAN, notification_id=notification.id)

    # PAY-4 : « une double notification du même paiement produit un seul
    # encaissement et une seule écriture ». La déduplication porte sur la
    # référence du tiers, seule chose qu'il garantit stable entre deux
    # envois du même événement.
    deja = AccPaymentNotification.objects.filter(
        tenant=tenant,
        external_reference=reference,
        state__in=[AccPaymentNotification.STATE_MATCHED, AccPaymentNotification.STATE_ORPHAN],
    ).first()
    if deja is not None:
        doublon = AccPaymentNotification.objects.create(
            tenant=tenant,
            intent=deja.intent,
            provider_code=provider_code,
            external_reference=reference,
            amount=amount,
            currency=currency,
            fee_amount=fee_amount,
            state=AccPaymentNotification.STATE_DUPLICATE,
            raw=raw,
        )
        return SettlementResult(outcome=OUTCOME_DUPLICATE, notification_id=doublon.id)

    intention = AccPaymentIntent.objects.filter(tenant=tenant, external_reference=reference).first()
    if intention is None:
        orpheline = AccPaymentNotification.objects.create(
            tenant=tenant,
            provider_code=provider_code,
            external_reference=reference,
            amount=amount,
            currency=currency,
            fee_amount=fee_amount,
            state=AccPaymentNotification.STATE_ORPHAN,
            raw=raw,
        )
        return SettlementResult(outcome=OUTCOME_NO_INTENT, notification_id=orpheline.id)

    return _settle(
        tenant,
        intention=intention,
        provider_code=provider_code,
        reference=reference,
        amount=amount,
        currency=currency,
        fee_amount=fee_amount,
        raw=raw,
        now=now,
    )


def _settle(
    tenant: Tenant,
    *,
    intention: AccPaymentIntent,
    provider_code: str,
    reference: str,
    amount: Decimal,
    currency: str,
    fee_amount: Decimal,
    raw: str,
    now: dt.datetime | None,
) -> SettlementResult:
    """La corrélation a réussi : c'est le seul chemin qui écrit.

    **PAY-6 : « un montant partiel produit un encaissement partiel et
    laisse la pièce ouverte pour le solde, SANS LETTRAGE FORCÉ ».** Rien
    ici ne compare le montant reçu au montant attendu pour décider d'agir :
    `register_payment` sait déjà encaisser un partiel et laisser la créance
    ouverte. Forcer l'égalité aurait transformé un versement partiel — cas
    parfaitement courant — en notification orpheline."""
    from apps.accounting.models import AccMove, AccPaymentNotification

    if intention.document_type != "accounting.AccMove":
        # Un ticket de caisse (`pos.PosOrder`) se règle par son propre
        # chemin : `accounting` n'a pas le droit d'importer `pos`, et
        # inventer ici une écriture pour une pièce qu'on ne connaît pas
        # serait précisément l'automatisme que l'interdit refuse.
        notification = AccPaymentNotification.objects.create(
            tenant=tenant,
            intent=intention,
            provider_code=provider_code,
            external_reference=reference,
            amount=amount,
            currency=currency,
            fee_amount=fee_amount,
            state=AccPaymentNotification.STATE_ORPHAN,
            raw=raw,
        )
        return SettlementResult(outcome=OUTCOME_ORPHAN, notification_id=notification.id)

    facture = AccMove.objects.filter(id=intention.document_id).first()
    if facture is None:
        notification = AccPaymentNotification.objects.create(
            tenant=tenant,
            intent=intention,
            provider_code=provider_code,
            external_reference=reference,
            amount=amount,
            currency=currency,
            fee_amount=fee_amount,
            state=AccPaymentNotification.STATE_ORPHAN,
            raw=raw,
        )
        return SettlementResult(outcome=OUTCOME_ORPHAN, notification_id=notification.id)

    with transaction.atomic():
        paiement = _register(
            facture, amount=amount, fee_amount=fee_amount, reference=reference, now=now
        )
        notification = AccPaymentNotification.objects.create(
            tenant=tenant,
            intent=intention,
            payment=paiement,
            provider_code=provider_code,
            external_reference=reference,
            amount=amount,
            currency=currency,
            fee_amount=fee_amount,
            state=AccPaymentNotification.STATE_MATCHED,
            raw=raw,
        )
        intention.state = type(intention).STATE_SETTLED
        intention.save(update_fields=["state"])

    return SettlementResult(
        outcome=OUTCOME_SETTLED,
        notification_id=notification.id,
        payment_id=paiement.id,
    )


def _register(
    facture: AccMove,
    *,
    amount: Decimal,
    fee_amount: Decimal,
    reference: str,
    now: dt.datetime | None,
) -> AccPayment:
    """Délègue à `register_payment`, qui sait déjà tout faire.

    Il porte l'écart de change, le lettrage partiel et la transition de
    `invoice_state`. Réécrire cela ici aurait produit une seconde façon
    d'encaisser une facture — donc deux comportements à maintenir, et un
    jour deux comportements différents."""
    from apps.accounting.models import AccJournal, AccPeriod, AccTenantDefaultAccount
    from apps.accounting.services.default_accounts import resolve_default_account
    from apps.accounting.services.payments import register_payment

    tenant = facture.tenant
    periode = (
        AccPeriod.objects.filter(tenant=tenant, state=AccPeriod.STATE_OPEN)
        .order_by("date_start")
        .first()
    )
    if periode is None:
        raise ValidationError(_("Aucune période ouverte : l'encaissement ne peut pas être écrit."))

    journal = (
        AccJournal.objects.filter(tenant=tenant, type=AccJournal.TYPE_BANK).order_by("code").first()
        or AccJournal.objects.filter(tenant=tenant, type=AccJournal.TYPE_CASH)
        .order_by("code")
        .first()
    )
    if journal is None:
        raise ValidationError(_("Aucun journal de trésorerie configuré."))

    # `resolve_default_account` plutôt qu'une résolution à la main : la
    # première rédaction de cette fonction refaisait le `filter(...).first()`
    # elle-même, ce qui perdait les deux moitiés utiles du service — le
    # repli par TYPE de compte quand rien n'est configuré, et
    # l'avertissement journalisé qui dit à l'exploitant que le repli a
    # servi. Deux résolveurs pour la même question finissent par répondre
    # deux choses différentes.
    tresorerie = resolve_default_account(
        tenant, AccTenantDefaultAccount.ROLE_BANK
    ) or resolve_default_account(tenant, AccTenantDefaultAccount.ROLE_CASH)
    ecart = resolve_default_account(tenant, AccTenantDefaultAccount.ROLE_CASH_DIFFERENCE)
    if tresorerie is None or ecart is None:
        raise ValidationError(
            _(
                "Comptes par défaut manquants (trésorerie, écart) : l'encaissement "
                "automatique ne peut pas être écrit sans eux."
            )
        )

    from apps.accounting.models import AccPayment

    paiement = register_payment(
        invoice=facture,
        period=periode,
        journal=journal,
        cash_account=tresorerie,
        gain_account=ecart,
        loss_account=ecart,
        date=(now.date() if now else dt.date.today()),
        amount=amount,
        method=AccPayment.METHOD_MOBILE_MONEY,
        reference_external=reference,
    )
    if fee_amount:
        _book_fee(
            facture,
            periode=periode,
            journal=journal,
            tresorerie=tresorerie,
            fee_amount=fee_amount,
            date=(now.date() if now else dt.date.today()),
            reference=reference,
        )
    return paiement


def _book_fee(
    facture: AccMove,
    *,
    periode: AccPeriod,
    journal: AccJournal,
    tresorerie: AccAccount,
    fee_amount: Decimal,
    date: dt.date,
    reference: str,
) -> AccMove:
    """La commission prélevée à la source, sur SON PROPRE compte de charge.

    **PAY-5 : « la commission étant isolée sur son propre compte de
    charge ».** Le mot « isolée » décide de tout : la fondre dans
    l'encaissement — en créditant la créance du brut et en débitant la
    trésorerie du net — ferait disparaître un coût contractuel dans un
    montant de règlement. Le contrôle de gestion ne le verrait plus, et le
    rapprochement du versement groupé ne retomberait jamais juste.

    **Une écriture SÉPARÉE, et non deux lignes de plus dans celle de
    l'encaissement.** `register_payment` produit une pièce dont l'équilibre
    est celui du règlement d'une créance ; y ajouter la commission
    obligerait à réécrire sa logique de lettrage et d'écart de change pour
    un cas qui n'est pas le sien. Deux pièces, reliées par la même
    `reference_external`, se lisent mieux qu'une pièce qui mélange deux
    faits."""
    from apps.accounting.models import AccTenantDefaultAccount
    from apps.accounting.services.default_accounts import resolve_default_account
    from apps.accounting.services.moves import add_line, create_draft_move, post_move

    tenant = facture.tenant
    compte_commission = resolve_default_account(tenant, AccTenantDefaultAccount.ROLE_PAYMENT_FEE)
    if compte_commission is None:
        raise ValidationError(
            _(
                "Aucun compte de commission d'encaissement configuré : la commission "
                "ne peut pas être isolée, et la fondre dans l'encaissement la rendrait "
                "invisible au contrôle de gestion."
            )
        )

    piece = create_draft_move(
        tenant=tenant,
        journal=journal,
        period=periode,
        date=date,
        narration=_("Commission d'encaissement — %(ref)s") % {"ref": reference},
    )
    add_line(
        piece,
        account=compte_commission,
        label=_("Commission d'encaissement"),
        debit=fee_amount,
    )
    add_line(
        piece,
        account=tresorerie,
        label=_("Commission prélevée à la source"),
        credit=fee_amount,
    )
    return post_move(piece)


__all__ = [
    "OUTCOME_DUPLICATE",
    "OUTCOME_NO_INTENT",
    "OUTCOME_ORPHAN",
    "OUTCOME_SETTLED",
    "SettlementResult",
    "receive_payment_notification",
]
