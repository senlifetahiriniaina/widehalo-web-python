"""C-4 — la colonne metier d'un document : une donnee, deux presentations.

**Ce que ce module resout.** Le commanditaire demande deux choses qui
paraissent distinctes : un kanban dont les colonnes suivent le processus,
et un statut lisible sur chaque ligne des listes d'operations. Ce sont la
MEME donnee vue de deux facons. Une seule declaration par document sert
les deux : les colonnes du kanban et la colonne « Statut » de la liste
sortent d'ici.

**Pourquoi une projection, et pas les etats eux-memes.** Mesure sur les
`choices` reels : `SalesOrder.state` a 10 etats, `LogShipment.state` 10,
`AccMove.invoice_state` 8. Un kanban a dix colonnes n'est pas lisible, et
le cahier demande des ecrans utilisables en mobilite. Les etats
techniques sont donc projetes sur cinq colonnes metier.

**Pourquoi la projection se DECLARE et ne se devine pas.** Le depot porte
deja un filtre qui devine une couleur d'apres les jetons du nom d'etat
(`core_extras.state_badge_class`), et T8 a mesure qu'il se trompe sur
**6 des 9 etats** du hub — `accepte` et `rejete` tombant tous deux en
gris, c'est-a-dire que le seul etat appelant un geste s'affichait comme
n'en appelant aucun. Deviner « termine » d'apres le texte d'un etat
referait la meme erreur, en plus visible.

**Le CRM ne passe pas par ici, et c'est deliberé.** Ses colonnes sont ses
`CrmStage` : un pipeline configurable par societe, ordonne par
`sequence`, que CRM-4 a livre. Le projeter sur cinq colonnes fixes
effacerait precisement ce que le client a configure. Son kanban existant
reste sa presentation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from django.utils.translation import gettext_lazy as _

COLONNE_EN_ATTENTE = "en_attente"
COLONNE_EN_COURS = "en_cours"
COLONNE_BLOQUE = "bloque"
COLONNE_TERMINE = "termine"
COLONNE_SANS_SUITE = "sans_suite"

#: Les cinq colonnes, dans l'ordre de lecture. Quatre viennent du
#: vocabulaire donne par le commanditaire ; la cinquieme — « Bloque » — est
#: decidee avec lui : `blocked`, `overdue` et `in_dispute` sont exactement
#: les lignes qui appellent un geste, et les fondre dans « en cours »
#: cacherait ce que l'ecran doit faire ressortir.
COLONNES: tuple[tuple[str, Any], ...] = (
    (COLONNE_EN_ATTENTE, _("En attente")),
    (COLONNE_EN_COURS, _("En cours")),
    (COLONNE_BLOQUE, _("Bloqué")),
    (COLONNE_TERMINE, _("Terminé")),
    (COLONNE_SANS_SUITE, _("Sans suite")),
)

_CODES = frozenset(code for code, _libelle in COLONNES)


@dataclass(frozen=True)
class Board:
    """La projection d'un document : quel champ porte l'etat, et ou va
    chaque etat."""

    state_field: str
    par_etat: Mapping[str, str]


_BOARDS: dict[str, Board] = {}


def register_board(model_label: str, board: Board) -> None:
    """Declare la projection d'un document, depuis `apps.py::ready()`.

    Refuse une colonne inconnue a la DECLARATION plutot qu'a l'affichage :
    une faute de frappe rendrait sinon une colonne fantome que personne ne
    verrait jamais, et les lignes qu'elle porte disparaitraient de
    l'ecran sans erreur."""
    inconnues = sorted(set(board.par_etat.values()) - _CODES)
    if inconnues:
        raise ValueError(
            f"{model_label} projette sur des colonnes inconnues : {inconnues}. "
            f"Colonnes valides : {sorted(_CODES)}."
        )
    existant = _BOARDS.get(model_label)
    if existant is not None and existant != board:
        raise ValueError(f"Deux projections declarees pour {model_label}.")
    _BOARDS[model_label] = board


def board_for(model_label: str) -> Board | None:
    return _BOARDS.get(model_label)


def registered_boards() -> frozenset[str]:
    """Les documents dotes d'une projection — lu par la garde."""
    return frozenset(_BOARDS)


def column_of(instance: Any) -> str | None:
    """La colonne metier de cet objet, ou `None` s'il n'en a pas.

    **Sert les DEUX presentations** : c'est le groupe de la carte en
    kanban, et la valeur de la colonne « Statut » en liste. Un objet rangé
    a un endroit en kanban et a un autre en liste serait un ecran qui se
    contredit."""
    board = _BOARDS.get(instance._meta.label)
    if board is None:
        return None
    return board.par_etat.get(getattr(instance, board.state_field, ""))


def column_label(code: str) -> Any:
    """Le libelle lisible d'une colonne."""
    for candidat, libelle in COLONNES:
        if candidat == code:
            return libelle
    return code


class StatutOperationnelMixin:
    """Donne a un modele la propriete `statut_operationnel`.

    **Pourquoi une propriete de modele.** Le composant de liste lit ses
    cellules par `getattr` — a l'affichage comme a l'export, et
    `_export_response` le documente : une colonne appuyee sur une
    `@property` (patron `Partner.roles_display`) fonctionne aux deux
    endroits, la ou `queryset.values()` echouerait. Une colonne « Statut »
    n'est donc pas un champ de base a ajouter par migration : c'est une
    lecture de la projection deja declaree.

    **C'est la MEME valeur que la colonne du kanban.** Une ligne rangee
    dans « Bloque » au tableau et affichee « En cours » en liste serait un
    ecran qui se contredit ; les deux passent par `column_of`."""

    @property
    def statut_operationnel(self) -> str:
        code = column_of(self)
        return str(column_label(code)) if code else ""
