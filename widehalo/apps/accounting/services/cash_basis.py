"""ACC-SMT1 (§1.1.1 du document annexe) : saisie simplifiee des mouvements
de caisse/banque pour un tenant au regime Impot Synthetique (< 200 M Ar de
CA). Design assume (cf. plan, etape A8) : PAS de ledger parallele — cette
fonction est une simple couche de confort au-dessus de la partie double
existante (`services/moves.py`), qui reste l'unique source de verite. Elle
traduit "de l'argent est entre/sorti" en une ecriture equilibree normale
(`AccMove`/`AccMoveLine`), de sorte que l'immuabilite, la numerotation et le
RLS de la phase 1 continuent de s'appliquer sans changement. Un futur ecran
(hors perimetre de cette etape) exposera cette fonction comme un formulaire
a 2 champs (montant + contrepartie) plutot que la saisie multi-lignes
normale de la comptabilite."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.accounting.models import AccAccount, AccJournal, AccMove, AccPeriod
from apps.accounting.services.moves import add_line, create_draft_move, post_move
from apps.core.models.tenant import Tenant

Direction = Literal["in", "out"]


def record_cash_movement(
    *,
    tenant: Tenant,
    journal: AccJournal,
    period: AccPeriod,
    date: dt.date,
    direction: Direction,
    amount: Decimal,
    cash_or_bank_account: AccAccount,
    counterpart_account: AccAccount,
    partner_id: UUID | None = None,
    label: str = "",
) -> AccMove:
    """Enregistre un encaissement (`direction="in"`) ou un decaissement
    (`direction="out"`) et publie immediatement l'ecriture qui en resulte.
    L'appelant raisonne uniquement en "entree"/"sortie" d'argent — la
    polarite debit/credit est resolue ici :
    - encaissement : debit `cash_or_bank_account`, credit `counterpart_account`
      (ex. debit Caisse, credit Ventes/Creance client soldee) ;
    - decaissement : credit `cash_or_bank_account`, debit `counterpart_account`
      (ex. credit Banque, debit Charge/Dette fournisseur soldee).

    `cash_or_bank_account.type` doit etre `AccAccount.TYPE_CASH` ou
    `AccAccount.TYPE_BANK` — c'est cette contrainte qui permet aux rapports
    ACC-SMT (`services/reports.py`) de retrouver ces mouvements sans table
    dediee supplementaire."""
    if amount <= 0:
        raise ValidationError(_("Le montant d'un mouvement de caisse doit être positif."))
    if cash_or_bank_account.type not in (AccAccount.TYPE_CASH, AccAccount.TYPE_BANK):
        raise ValidationError(_("Le compte de trésorerie doit être de type caisse ou banque."))

    move = create_draft_move(
        tenant=tenant,
        journal=journal,
        period=period,
        date=date,
        move_type=AccMove.TYPE_ENTRY,
        partner_id=partner_id,
        narration=label,
    )

    if direction == "in":
        add_line(
            move,
            account=cash_or_bank_account,
            label=label,
            debit=amount,
            partner_id=partner_id,
        )
        add_line(
            move,
            account=counterpart_account,
            label=label,
            credit=amount,
            partner_id=partner_id,
        )
    elif direction == "out":
        add_line(
            move,
            account=counterpart_account,
            label=label,
            debit=amount,
            partner_id=partner_id,
        )
        add_line(
            move,
            account=cash_or_bank_account,
            label=label,
            credit=amount,
            partner_id=partner_id,
        )
    else:
        raise ValidationError(_("Sens de mouvement invalide : 'in' ou 'out' attendu."))

    return post_move(move)
