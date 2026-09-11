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
from apps.core.services.presentation import (
    COLONNE_BLOQUE,
    COLONNE_EN_ATTENTE,
    COLONNE_EN_COURS,
    COLONNE_SANS_SUITE,
    COLONNE_TERMINE,
    Board,
    register_board,
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


#: C-4 — les 10 etats d'une commande projetes sur cinq colonnes lisibles.
#: `blocked` a sa propre colonne : une commande bloquee pour encours client
#: est exactement la ligne qu'un commercial doit traiter, et la noyer dans
#: « en cours » la rendrait invisible.
_ORDER_BOARD = Board(
    state_field="state",
    par_etat={
        "draft": COLONNE_EN_ATTENTE,
        "sent": COLONNE_EN_ATTENTE,
        "confirmed": COLONNE_EN_COURS,
        "in_preparation": COLONNE_EN_COURS,
        "partially_delivered": COLONNE_EN_COURS,
        "delivered": COLONNE_EN_COURS,
        "invoiced": COLONNE_TERMINE,
        "closed": COLONNE_TERMINE,
        "blocked": COLONNE_BLOQUE,
        "cancelled": COLONNE_SANS_SUITE,
    },
)

#: Un devis expire n'est pas refuse : il n'a simplement plus de suite. Les
#: deux tombent en « sans suite », mais le libelle de l'etat reste lisible
#: sur la carte — la colonne range, elle ne remplace pas l'etat.
_QUOTATION_BOARD = Board(
    state_field="state",
    par_etat={
        "draft": COLONNE_EN_ATTENTE,
        "sent": COLONNE_EN_COURS,
        "accepted": COLONNE_TERMINE,
        "declined": COLONNE_SANS_SUITE,
        "expired": COLONNE_SANS_SUITE,
    },
)


def register() -> None:
    register_next_steps("sales.SalesOrder", _order_steps)
    register_next_steps("sales.SalesQuotation", _quotation_steps)
    register_board("sales.SalesOrder", _ORDER_BOARD)
    register_board("sales.SalesQuotation", _QUOTATION_BOARD)
