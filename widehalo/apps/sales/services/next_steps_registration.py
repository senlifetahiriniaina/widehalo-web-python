"""C-3 — les suites possibles d'un devis et d'une commande de vente.

Deux mecanismes distincts dans le meme module, et c'est pourquoi le socle
est un registre plutot qu'une introspection : `SalesOrder` porte une
machine `django_fsm`, `SalesQuotation` un `CharField` ordinaire dont les
transitions vivent dans `services/quotations.py`.

Les libelles sont ecrits ici parce que `core` ne peut pas les deviner : la
transition s'appelle `confirm`, l'exploitant lit « Confirmer la commande ».
"""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from apps.core.models.user import User
from apps.core.services.next_steps import (
    NextStep,
    declared_next_steps,
    fsm_next_steps,
    register_next_steps,
)
from apps.sales.models import SalesQuotation

#: Le droit d'ECRITURE de C-1 : les memes codenames que l'API et l'ecran.
_ORDER_WRITE = "sales.change_salesorder"
_QUOTATION_WRITE = "sales.change_salesquotation"

_ORDER_LABELS = {
    "send": _("Envoyer au client"),
    "confirm": _("Confirmer la commande"),
    "start_preparation": _("Lancer la préparation"),
    "mark_partially_delivered": _("Marquer partiellement livrée"),
    "mark_delivered": _("Marquer livrée"),
    "mark_invoiced": _("Facturer"),
    "close": _("Clôturer"),
    "cancel": _("Annuler"),
    "block_for_credit": _("Bloquer pour encours client"),
    "unblock": _("Débloquer"),
}

#: `SalesQuotation` n'a pas de machine a etats : la table dit, pour chaque
#: etat, ce que l'ecran propose (`_QUOTATION_ACTIONS` de `views.py`). Une
#: garde verifie que les etats cites existent dans les `choices` du champ.
_QUOTATION_STEPS = {
    SalesQuotation.STATE_DRAFT: [NextStep("send", str(_("Envoyer au client")))],
    SalesQuotation.STATE_SENT: [
        NextStep("accept", str(_("Marquer acceptée"))),
        NextStep("decline", str(_("Marquer refusée"))),
    ],
    SalesQuotation.STATE_ACCEPTED: [NextStep("convert_to_order", str(_("Convertir en commande")))],
}


def _order_steps(instance: Any, user: User) -> list[NextStep]:
    return fsm_next_steps(
        instance,
        user,
        field_name="state",
        write_codename=_ORDER_WRITE,
        labels={code: str(libelle) for code, libelle in _ORDER_LABELS.items()},
    )


def _quotation_steps(instance: Any, user: User) -> list[NextStep]:
    return declared_next_steps(
        instance,
        user,
        state_field="state",
        write_codename=_QUOTATION_WRITE,
        par_etat=_QUOTATION_STEPS,
    )


def register() -> None:
    register_next_steps("sales.SalesOrder", _order_steps)
    register_next_steps("sales.SalesQuotation", _quotation_steps)
