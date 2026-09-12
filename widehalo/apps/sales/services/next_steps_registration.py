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
    LigneResume,
    register_board,
)
from apps.partners.services.public import get_partner_display_names
from apps.sales.models import SalesQuotation

#: Le droit d'ECRITURE de C-1 : les memes codenames que l'API et l'ecran.
_ORDER_WRITE = "sales.change_salesorder"
_QUOTATION_WRITE = "sales.change_salesquotation"

#: Les transitions qui sont des ACTIONS D'ECRAN, et elles seules. Une
#: transition absente n'est pas proposee — c'est un jeu ferme depuis que la
#: mesure a montre ce que le repli permissif coutait.
#:
#: `block_for_credit` n'y figure pas, et c'est mesure : aucune branche de
#: `apps/sales/views.py` ne la traite, aucun service `block_order` n'existe,
#: et la transition n'est atteinte QUE comme effet de bord de
#: `confirm_order` quand l'encours client est depasse
#: (`apps/sales/services/orders.py:330`). La proposer en bouton offrait un
#: geste que le produit n'a jamais su faire.
#:
#: `cancel` n'y figure pas non plus, pour une autre raison mesuree :
#: `cancel_order` EXIGE un motif, et le bandeau ne poste qu'une action sans
#: champ de saisie — le bouton rendait donc systematiquement « Un motif est
#: obligatoire pour annuler une commande ». L'ecran porte deja son propre
#: formulaire d'annulation, avec le champ qu'il faut ; le bandeau annonce
#: la suite a prendre, pas les issues de secours.
_ORDER_LABELS = {
    "send": _("Envoyer au client"),
    "confirm": _("Confirmer la commande"),
    "start_preparation": _("Lancer la préparation"),
    "mark_partially_delivered": _("Marquer partiellement livrée"),
    "mark_delivered": _("Marquer livrée"),
    "mark_invoiced": _("Facturer"),
    "close": _("Clôturer"),
    "unblock": _("Débloquer"),
}

#: Le vocabulaire de l'ECRAN, quand il differe du nom de la transition.
#: `apps/sales/views.py:365-374` attend `deliver_partial`, `deliver_full` et
#: `invoice` ; le bandeau postait les noms de transition, aucune branche ne
#: correspondait, et trois boutons ne faisaient rien EN SILENCE. Sur une
#: commande livree, deux boutons « Facturer » voisinaient : celui de
#: l'ecran marchait, celui du bandeau non.
_ORDER_ACTIONS_ECRAN = {
    "mark_partially_delivered": "deliver_partial",
    "mark_delivered": "deliver_full",
    "mark_invoiced": "invoice",
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
        actions=_ORDER_ACTIONS_ECRAN,
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
def _enrichir_partenaires(objets: list[Any]) -> None:
    """Resout le nom des tiers des lignes rendues, EN UNE REQUETE.

    **Ce que l'exploitant voyait avant.** La colonne « Partenaire » rendait
    `partner_id`, c'est-a-dire un UUID — et comme ce sont des UUIDv7,
    prefixes par un horodatage, deux commandes du meme jour affichaient les
    memes quatorze premiers caracteres : la colonne ne distinguait rien.

    `partner_id` est un `UUIDField`, jamais une cle etrangere : la regle de
    couplage n°1 interdit a `sales` de connaitre le modele `Partner`. Le nom
    passe donc par la surface publique de `partners`, et EN LOT — un appel
    par ligne couterait vingt-cinq requetes par page."""
    noms = get_partner_display_names({objet.partner_id for objet in objets})
    for objet in objets:
        objet.partner_display = noms.get(str(objet.partner_id), "")


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
    enrichir=_enrichir_partenaires,
    resume=(
        LigneResume(label=_("Client"), attribut="partner_display"),
        LigneResume(label=_("Montant"), attribut="amount_total_mga", format="mga"),
    ),
    fiche=(
        LigneResume(label=_("Référence"), attribut="reference"),
        LigneResume(label=_("Client"), attribut="partner_display"),
        LigneResume(label=_("Commercial"), attribut="salesperson"),
        LigneResume(label=_("Date"), attribut="date"),
        LigneResume(label=_("Montant"), attribut="amount_total_mga", format="mga"),
        LigneResume(label=_("Statut"), attribut="state"),
    ),
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
    enrichir=_enrichir_partenaires,
    resume=(
        LigneResume(label=_("Client"), attribut="partner_display"),
        LigneResume(label=_("Montant"), attribut="amount_total_mga", format="mga"),
    ),
    fiche=(
        LigneResume(label=_("Référence"), attribut="reference"),
        LigneResume(label=_("Client"), attribut="partner_display"),
        LigneResume(label=_("Date"), attribut="date"),
        LigneResume(label=_("Validité"), attribut="validity_date"),
        LigneResume(label=_("Montant"), attribut="amount_total_mga", format="mga"),
        LigneResume(label=_("Statut"), attribut="state"),
    ),
)


def register() -> None:
    register_next_steps("sales.SalesOrder", _order_steps)
    register_next_steps("sales.SalesQuotation", _quotation_steps)
    register_board("sales.SalesOrder", _ORDER_BOARD)
    register_board("sales.SalesQuotation", _QUOTATION_BOARD)
