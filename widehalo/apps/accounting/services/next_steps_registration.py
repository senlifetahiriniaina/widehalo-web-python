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


def register() -> None:
    register_next_steps("accounting.AccMove", _invoice_steps)
