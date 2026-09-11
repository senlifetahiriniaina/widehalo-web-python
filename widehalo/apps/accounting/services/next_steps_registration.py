"""C-3 — les suites possibles d'une facture client.

`AccMove.invoice_state` est une machine `django_fsm`. Le droit d'ecriture
retenu est `change_accmove`, celui que porte deja l'ecran et l'endpoint —
et non `validate_accmove`, qui ne couvrirait qu'une des sept transitions.
Proposer une suite n'est pas l'autoriser : `attempt_transition` reverifie,
et l'ecran garde son propre refus par action (C-1)."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from apps.core.models.user import User
from apps.core.services.next_steps import NextStep, fsm_next_steps, register_next_steps
from apps.core.services.presentation import (
    COLONNE_BLOQUE,
    COLONNE_EN_ATTENTE,
    COLONNE_EN_COURS,
    COLONNE_SANS_SUITE,
    COLONNE_TERMINE,
    Board,
    register_board,
)

_WRITE = "accounting.change_accmove"

#: Les transitions de facture qui sont des ACTIONS D'ECRAN. Jeu ferme :
#: une transition absente n'est pas proposee.
#:
#: **Cinq transitions ont ete retirees, chacune pour une raison mesuree, et
#: deux d'entre elles etaient dangereuses.**
#:
#: - `mark_paid` et `mark_paid_partially` sont des CONSEQUENCES de
#:   `register_payment` (`apps/accounting/services/payments.py:131-133`).
#:   Les proposer en boutons permettait de marquer une facture reglee
#:   **sans aucune ecriture comptable** — un ecran ne doit pas offrir un
#:   raccourci qui casse la partie double.
#: - `submit_for_validation` n'est pas un geste separe : `validate_invoice`
#:   l'execute lui-meme avant de valider
#:   (`apps/accounting/services/invoices.py:310-315`). Il reste donc dans
#:   le jeu, mais sous le libelle de ce qu'il DECLENCHE et en postant
#:   l'action de l'ecran — sans quoi une facture en brouillon ne se verrait
#:   proposer aucune suite, alors que sa suite evidente est de la valider.
#:   C'est la mesure qui l'a montre : la premiere version de ce jeu ferme
#:   rendait le bandeau vide sur tout brouillon.
#: - `mark_overdue` et `mark_in_dispute` n'ont **aucun appelant de
#:   production** dans tout le depot : les proposer promettait une action
#:   que rien n'execute. Reserve ecrite : une facture ne devient donc
#:   jamais « en retard » aujourd'hui, et la colonne « Bloque » du tableau
#:   des factures reste structurellement vide. C'est une dette declaree,
#:   pas un oubli.
#: `cancel` est absent pour la meme raison qu'en ventes : `cancel_invoice`
#: exige un motif (`apps/accounting/services/invoices.py:338`) et le
#: bandeau ne poste aucun champ de saisie. L'ecran de la facture porte son
#: formulaire d'annulation avec le motif ; un bouton qui echouerait a tous
#: les coups serait pire que pas de bouton.
_LABELS = {
    "submit_for_validation": _("Valider la facture"),
    "validate": _("Valider la facture"),
}

#: Le vocabulaire de l'ECRAN. `apps/accounting/views.py:131` ne connait que
#: `validate`, `cancel` et `register_payment` : une facture en brouillon
#: passe donc par la meme action que celle a valider, et le service fait
#: les deux transitions.
_ACTIONS_ECRAN = {"submit_for_validation": "validate"}

#: Le droit exige par CHAQUE action, en miroir exact de `_DROITS_FACTURE`
#: (`apps/accounting/views.py:94-98`). Sans lui, un role dote de `change`
#: mais pas de `validate` se voyait proposer « Valider la facture » et
#: recevait 403 : l'ecran promettait ce que la garde refusait.
_DROITS_ECRAN = {
    "submit_for_validation": "accounting.validate_accmove",
    "validate": "accounting.validate_accmove",
}


def _invoice_steps(instance: Any, user: User) -> list[NextStep]:
    return fsm_next_steps(
        instance,
        user,
        field_name="invoice_state",
        write_codename=_WRITE,
        labels={code: str(libelle) for code, libelle in _LABELS.items()},
        actions=_ACTIONS_ECRAN,
        permissions=_DROITS_ECRAN,
    )


#: C-4 — `overdue` et `in_dispute` vont en « Bloque », pas en « En cours ».
#: Une facture en retard ou en contentieux est precisement celle qu'un
#: comptable doit traiter ; la ranger avec les factures qui suivent leur
#: cours reviendrait a la cacher.
_INVOICE_BOARD = Board(
    state_field="invoice_state",
    par_etat={
        "draft": COLONNE_EN_ATTENTE,
        "to_validate": COLONNE_EN_ATTENTE,
        "validated": COLONNE_EN_COURS,
        "paid_partially": COLONNE_EN_COURS,
        "overdue": COLONNE_BLOQUE,
        "in_dispute": COLONNE_BLOQUE,
        "paid": COLONNE_TERMINE,
        "cancelled": COLONNE_SANS_SUITE,
    },
)


def register() -> None:
    register_next_steps("accounting.AccMove", _invoice_steps)
    register_board("accounting.AccMove", _INVOICE_BOARD)
