"""T6 (bloc E, BNK-4 et BNK-5) — l'émission d'un ordre de virement de paie.

**Ce que la mesure a trouvé, et c'est le motif « rien de décoratif » sous
sa forme la plus complète.** `services/mobile_money.py` produit un fichier
de virement depuis PAY-VIR/PAY-MM1 — et **aucun appelant de production ne
l'invoque**. Ni vue, ni API, ni commande : les deux seuls appelants du
dépôt sont des tests. La fonctionnalité était donc écrite, documentée,
testée, et inatteignable depuis l'application. Un exploitant ne pouvait pas
payer ses salariés.

BNK-4 rend cela bloquant : « un ordre de virement **exporté** est rattaché
aux pièces qu'il règle » suppose qu'exporter soit possible.

**Ce module ne recopie aucun format.** Il compose l'ordre — quels bulletins,
quel bénéficiaire, quel montant —, le confie à `accounting` qui le tient et
l'exporte, et rend le fichier. Le format du fichier vit d'un seul côté,
celui qui porte l'ordre : deux générateurs pour la même chose finiraient par
en produire deux différents.

**Le montant est le MOUVEMENT, jamais la valeur pleine** (L14/PAY-9,
repris de `mobile_money.py`) : un bulletin rectificatif ne doit ordonner
que l'écart, sans quoi le salarié serait payé deux fois.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

import apps.accounting.services.public as accounting_public
from apps.payroll.models import PayBatch, PayPayslip
from apps.payroll.services.regularization import regularization_movement

if TYPE_CHECKING:
    from uuid import UUID

#: Le type de pièce que ces ordres règlent. Une chaîne, jamais une classe :
#: c'est `accounting` qui la stocke, et il n'a pas le droit d'importer
#: `payroll` (règle de couplage n°1).
PAYSLIP_DOCUMENT_TYPE = "payroll.PayPayslip"


def emit_payroll_transfer_order(
    batch: PayBatch,
    *,
    bank_account_id: UUID,
    method: str,
    coordinates_by_employee: dict[str, str],
    execution_date: dt.date | None = None,
) -> dict[str, Any]:
    """Émet l'ordre de virement d'un lot de paie, et rend son fichier.

    **Les bulletins ANNULÉS sont exclus**, comme dans les générateurs
    d'origine : ordonner le virement d'un bulletin annulé paierait quelqu'un
    pour un bulletin qui n'existe plus.

    **Un montant nul ou négatif est exclu, pas refusé.** Un bulletin
    rectificatif dont le mouvement est nul — l'écart a déjà été payé — n'a
    rien à ordonner ; faire échouer tout le lot pour lui empêcherait de
    payer les autres, ce qui est exactement le défaut que BNK-2 corrige de
    l'autre côté.

    Lève si, une fois ces exclusions faites, il ne reste rien : un ordre
    vide attendrait indéfiniment un débit qui n'arrivera pas."""
    if method not in (PayPayslip.PAYMENT_MOBILE_MONEY, PayPayslip.PAYMENT_BANK):
        raise ValidationError(
            _("Voie de paiement inconnue pour un ordre de virement : %(voie)s.") % {"voie": method}
        )

    lignes: list[dict[str, Any]] = []
    for bulletin in batch.payslips.filter(payment_method=method).exclude(
        state=PayPayslip.STATE_CANCELLED
    ):
        montant = Decimal(regularization_movement(bulletin, "net_to_pay"))
        if montant <= 0:
            continue
        lignes.append(
            {
                "document_type": PAYSLIP_DOCUMENT_TYPE,
                "document_id": bulletin.id,
                # Le bénéficiaire est désigné par son IDENTIFIANT et sa
                # coordonnée de paiement — jamais par une donnée de paie
                # (BNK-5). Ce qui n'entre pas ici ne peut pas sortir dans le
                # fichier.
                "beneficiary_label": str(bulletin.employee_id),
                "beneficiary_account": coordinates_by_employee.get(str(bulletin.employee_id), ""),
                "amount": montant,
                "reference": bulletin.reference,
            }
        )

    if not lignes:
        raise ValidationError(
            _(
                "Aucun bulletin à virer pour cette voie : l'ordre serait vide et "
                "attendrait un débit qui n'arrivera jamais."
            )
        )

    resultat = accounting_public.record_transfer_order(
        batch.tenant,
        bank_account_id=bank_account_id,
        execution_date=execution_date or batch.period.date_to,
        lines=lignes,
        origin=accounting_public.TRANSFER_ORIGIN_PAYROLL,
        currency="MGA",
    )
    if resultat is None:
        raise ValidationError(
            _("Compte bancaire introuvable : l'ordre de virement ne peut pas être émis.")
        )
    return resultat


__all__ = ["PAYSLIP_DOCUMENT_TYPE", "emit_payroll_transfer_order"]
