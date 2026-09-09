"""T6 (bloc E, BNK-4) — l'ordre de virement, de sa composition à son débit.

**Le critère** : « un ordre de virement exporté est rattaché aux pièces
qu'il règle, et son état de remise est suivi jusqu'au rapprochement du
débit correspondant. »

**Ce que la mesure a trouvé, et c'est un vide, pas un manque.** Rien de tel
n'existait. `payroll` produit un fichier de virement depuis PAY-VIR : une
chaîne de caractères, rendue à l'appelant, rattachée à aucune pièce et
suivie par personne. Un ordre remis à la banque et jamais exécuté ne se
voyait donc qu'au moment où un salarié signalait ne pas avoir été payé.

**Le fichier exporté ne porte que trois choses.** Bénéficiaire, montant,
référence — la discipline de BNK-5, appliquée à tout ordre et pas
seulement à celui de la paie : ce qui ne figure pas dans le fichier ne peut
pas fuir, et le jour où un ordre d'achats sera exporté, il le sera sous la
même règle sans qu'on ait à y repenser.

**Ce module ne poste aucune écriture, et c'est délibéré.** Un ordre de
virement est une INSTRUCTION donnée à la banque, pas un fait comptable :
l'écriture naît du débit constaté au relevé, par le rapprochement bancaire
qui existe déjà. Écrire à l'émission ferait apparaître une sortie d'argent
que la banque n'a pas encore exécutée — et l'interdit du §4.4 vise
exactement ce genre d'anticipation.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounting.models import (
    AccAccount,
    AccBankStatementLine,
    AccTransferOrder,
    AccTransferOrderLine,
)

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant

#: Les colonnes du fichier exporté, et elles sont FERMÉES.
#:
#: BNK-5 ne parle que de l'ordre de paie ; la règle est appliquée à tous
#: parce qu'une exception ne se justifierait par rien — un ordre d'achats
#: n'a pas plus de raison de porter le détail d'une facture qu'un ordre de
#: paie celui d'un bulletin. Une colonne de plus se voit ici, et le test de
#: contenu la refuse.
EXPORT_FIELDNAMES = ["beneficiary", "account", "amount", "reference"]


def _assert_origin_vocabulary_matches() -> None:
    """Le jeu exposé par `services/public.py` et celui du modèle disent la
    même chose, ou la construction échoue.

    Deux vocabulaires pour la même notion — l'un lisible par `payroll`,
    l'autre stocké — ne se contredisent jamais bruyamment : ils divergent
    d'une valeur, et un ordre de paie cesse simplement d'apparaître dans le
    filtre par origine. Même discipline que les six familles d'erreur et les
    huit opérations du hub."""
    from apps.accounting.services import public

    expose = {
        public.TRANSFER_ORIGIN_PAYROLL,
        public.TRANSFER_ORIGIN_PURCHASE,
        public.TRANSFER_ORIGIN_MANUAL,
    }
    declare = {code for code, _label in AccTransferOrder.ORIGIN_CHOICES}
    if expose != declare:
        raise ValidationError(
            _(
                "Les origines d'ordre de virement exposées (%(expose)s) et "
                "déclarées (%(declare)s) divergent."
            )
            % {"expose": sorted(expose), "declare": sorted(declare)}
        )


def create_transfer_order(
    tenant: Tenant,
    *,
    bank_account: AccAccount,
    execution_date: dt.date,
    lines: list[dict[str, Any]],
    origin: str = AccTransferOrder.ORIGIN_MANUAL,
    currency: str = "MGA",
) -> AccTransferOrder:
    """Compose un ordre à partir des pièces qu'il règle.

    `lines` : `[{"document_type", "document_id", "beneficiary_label",
    "beneficiary_account", "amount", "reference"}]`. La pièce est désignée
    par un couple opaque, jamais par un objet — `accounting` n'a pas le
    droit d'importer `payroll`, et un ordre d'achats désignera des factures
    fournisseur par le même chemin.

    **Le total est CALCULÉ, jamais reçu.** Le faire passer en paramètre
    aurait permis à un ordre d'annoncer une somme qui n'est pas celle de
    ses lignes — c'est-à-dire à la banque de débiter autre chose que ce que
    nous croyons régler, sans qu'aucun contrôle ne le voie.

    **Un ordre vide est refusé.** Il produirait un fichier sans ligne, que
    la banque rejetterait, et surtout il attendrait pour toujours un débit
    de zéro qui n'apparaîtra jamais au relevé — donc un ordre en vol
    permanent dans l'écran de suivi."""
    if bank_account.type != AccAccount.TYPE_BANK:
        raise ValidationError(
            _("Le compte %(code)s n'est pas un compte de banque : un ordre de virement en part.")
            % {"code": bank_account.code}
        )
    if not lines:
        raise ValidationError(
            _(
                "Un ordre de virement sans ligne ne règle rien et attendrait "
                "indéfiniment un débit qui n'arrivera pas."
            )
        )

    montants = [Decimal(ligne["amount"]) for ligne in lines]
    if any(montant <= 0 for montant in montants):
        raise ValidationError(_("Une ligne d'ordre de virement porte un montant nul ou négatif."))

    with transaction.atomic():
        ordre = AccTransferOrder.objects.create(
            tenant=tenant,
            bank_account=bank_account,
            origin=origin,
            execution_date=execution_date,
            currency=currency,
            total_amount=sum(montants, Decimal(0)),
        )
        AccTransferOrderLine.objects.bulk_create(
            [
                AccTransferOrderLine(
                    tenant=tenant,
                    order=ordre,
                    document_type=ligne["document_type"],
                    document_id=ligne["document_id"],
                    beneficiary_label=ligne.get("beneficiary_label", ""),
                    beneficiary_account=ligne.get("beneficiary_account", ""),
                    amount=Decimal(ligne["amount"]),
                    reference=ligne.get("reference", ""),
                )
                for ligne in lines
            ]
        )
    return ordre


def export_transfer_order(order: AccTransferOrder, *, now: dt.datetime | None = None) -> str:
    """Produit le fichier remis à la banque, et fige l'ordre.

    **Ré-exporter est permis, et ne change rien.** Une banque perd un
    fichier, un exploitant le remet : refuser l'obligerait à recomposer un
    ordre identique sous une autre référence, donc à risquer un double
    débit. Le contenu est reproduit à l'identique et `exported_at` garde la
    date du PREMIER export — c'est celle qui compte pour savoir depuis
    combien de temps l'argent aurait dû partir.

    **Rien de ce qui n'est pas dans `EXPORT_FIELDNAMES` ne sort.** C'est la
    discipline de BNK-5 étendue à tous les ordres : bénéficiaire, compte,
    montant, référence."""
    if order.state == AccTransferOrder.STATE_RECONCILED:
        raise ValidationError(
            _(
                "Cet ordre est déjà rapproché de son débit : le ré-exporter "
                "exposerait à un second virement du même montant."
            )
        )

    tampon = io.StringIO()
    writer = csv.DictWriter(tampon, fieldnames=EXPORT_FIELDNAMES)
    writer.writeheader()
    for ligne in order.lines.all().order_by("beneficiary_label"):
        writer.writerow(
            {
                "beneficiary": ligne.beneficiary_label,
                "account": ligne.beneficiary_account,
                "amount": str(ligne.amount),
                "reference": ligne.reference,
            }
        )

    if order.state == AccTransferOrder.STATE_DRAFT:
        order.state = AccTransferOrder.STATE_EXPORTED
        order.exported_at = now or timezone.now()
        order.save(update_fields=["state", "exported_at"])
    return tampon.getvalue()


def mark_remitted(order: AccTransferOrder, *, now: dt.datetime | None = None) -> AccTransferOrder:
    """L'exploitant atteste avoir déposé l'ordre à la banque.

    **Attesté, jamais déduit.** Aucune banque ne nous dit qu'elle a reçu le
    fichier ; le déduire de l'export ferait passer pour remis un ordre resté
    sur un poste de travail, et l'écran de suivi montrerait un retard de la
    banque là où il n'y a qu'un oubli chez nous."""
    if order.state != AccTransferOrder.STATE_EXPORTED:
        raise ValidationError(
            _("Seul un ordre exporté peut être marqué remis ; celui-ci est « %(etat)s ».")
            % {"etat": order.get_state_display()}
        )
    order.state = AccTransferOrder.STATE_REMITTED
    order.remitted_at = now or timezone.now()
    order.save(update_fields=["state", "remitted_at"])
    return order


def reconcile_transfer_order(
    order: AccTransferOrder, statement_line: AccBankStatementLine
) -> AccTransferOrder:
    """Rattache le DÉBIT constaté au relevé, et clôt le parcours.

    **C'est la moitié du critère que rien ne portait** — « son état de
    remise est suivi JUSQU'AU RAPPROCHEMENT DU DÉBIT correspondant ».

    Trois refus, et chacun ferme une façon différente de se tromper :

    1. Un mouvement ENTRANT n'est pas l'exécution d'un ordre de virement.
       Un ordre fait sortir de l'argent ; le rapprocher d'un encaissement
       ferait disparaître deux mouvements réels d'un coup.
    2. Un montant qui diffère. Une banque qui débite autre chose que ce
       qu'on lui a demandé est précisément l'incident que ce suivi existe
       pour rendre visible ; l'absorber en silence le rendrait invisible.
    3. Une ligne de relevé déjà rattachée à un autre ordre — sans quoi deux
       ordres se déclareraient réglés par le même débit."""
    if statement_line.direction != AccBankStatementLine.DIRECTION_OUT:
        raise ValidationError(
            _(
                "Un ordre de virement se rapproche d'un mouvement SORTANT ; "
                "cette ligne de relevé est entrante."
            )
        )
    if statement_line.amount_mga != order.total_amount:
        raise ValidationError(
            _(
                "Le débit de %(debit)s ne correspond pas au montant de l'ordre "
                "(%(ordre)s) : l'écart doit être tranché avant tout "
                "rapprochement."
            )
            % {"debit": statement_line.amount_mga, "ordre": order.total_amount}
        )
    deja = (
        AccTransferOrder.objects.filter(statement_line=statement_line).exclude(id=order.id).first()
    )
    if deja is not None:
        raise ValidationError(
            _("Ce débit règle déjà l'ordre %(ref)s.") % {"ref": deja.reference or deja.id}
        )

    order.statement_line = statement_line
    order.state = AccTransferOrder.STATE_RECONCILED
    order.save(update_fields=["statement_line", "state"])
    return order


def orders_in_flight(tenant: Tenant, *, as_of: dt.date | None = None) -> list[AccTransferOrder]:
    """Les ordres remis dont le débit n'est pas apparu.

    **C'est la question que BNK-4 fait poser**, et le seul état où une
    alerte a du sens : un ordre exporté mais jamais remis attend un geste de
    notre côté, un ordre rapproché est clos. Entre les deux, l'argent est
    censé être parti et ne se voit nulle part — c'est là qu'un suivi sert.

    Trié par date d'exécution : le plus ancien en vol est celui sur lequel
    il faut appeler la banque."""
    queryset = AccTransferOrder.objects.filter(tenant=tenant, state=AccTransferOrder.STATE_REMITTED)
    if as_of is not None:
        queryset = queryset.filter(execution_date__lte=as_of)
    return list(queryset.order_by("execution_date"))


__all__ = [
    "EXPORT_FIELDNAMES",
    "create_transfer_order",
    "export_transfer_order",
    "mark_remitted",
    "orders_in_flight",
    "reconcile_transfer_order",
]
