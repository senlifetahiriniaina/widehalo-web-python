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

_LABELS = {
    "submit_for_validation": _("Soumettre à validation"),
    "validate": _("Valider la facture"),
    "mark_paid": _("Marquer réglée"),
    "mark_paid_partially": _("Marquer partiellement réglée"),
    "mark_overdue": _("Marquer en retard"),
    "mark_in_dispute": _("Marquer en litige"),
    "cancel": _("Annuler"),
}


def _invoice_steps(instance: Any, user: User) -> list[NextStep]:
    return fsm_next_steps(
        instance,
        user,
        field_name="invoice_state",
        write_codename=_WRITE,
        labels={code: str(libelle) for code, libelle in _LABELS.items()},
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
