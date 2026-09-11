"""C-4 — la colonne metier d'un document : une donnee, deux presentations.

**Ce que ce module resout.** Le commanditaire demande deux choses qui
paraissent distinctes : un kanban dont les colonnes suivent le processus,
et un statut lisible sur chaque ligne des listes d'operations. Ce sont la
MEME donnee vue de deux facons. Une seule declaration par document sert
les deux : le champ d'etat qu'elle nomme donne les colonnes du kanban
(`column_of`) et le statut ecrit sur chaque ligne
(`StatutOperationnelMixin`).

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
from typing import Any, cast

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

    C'est le groupe de la carte en kanban. Le statut ecrit sur la ligne,
    lui, est `StatutOperationnelMixin.statut_operationnel` — les deux se
    lisent sur le MEME champ, si bien qu'une ligne rangee dans « Bloque »
    ne peut pas porter un statut qui la dirait ailleurs."""
    board = _BOARDS.get(instance._meta.label)
    if board is None:
        return None
    return board.par_etat.get(getattr(instance, board.state_field, ""))


class StatutOperationnelMixin:
    """Donne a un modele la propriete `statut_operationnel` : le statut
    LISIBLE d'une ligne d'operation.

    **Ce que la mesure a corrige, et pourquoi cette propriete ne rend pas
    la colonne du kanban.** La premiere version rendait le libelle de la
    colonne metier — « En attente », « En cours ». Mesure sur l'ecran
    produit : la carte du kanban affichait alors, sous son titre,
    exactement le mot deja ecrit en tete de la colonne qui la contient. Du
    decor qui a l'air d'informer. Cette propriete rend donc l'etat PROPRE
    de la ligne (« Brouillon », « Confirmee », « Annulee ») : le kanban
    groupe en cinq colonnes metier, et chaque carte dit ou elle en est a
    l'interieur de sa colonne.

    **Et elle rend la liste lisible, ce qui etait la demande.** Mesure sur
    `/sales/orders/` : la colonne « Statut » etait declaree `key="state"`,
    donc rendue par `getattr` — elle affichait `draft`, le code technique
    anglais, dans une interface francaise. Le statut EXISTAIT sans etre
    lisible ; c'est l'entete que ma mesure precedente avait comptee, pas sa
    valeur.

    **Pourquoi une propriete de modele.** Le composant de liste lit ses
    cellules par `getattr` — a l'affichage comme a l'export, et
    `_export_response` le documente : une colonne appuyee sur une
    `@property` (patron `Partner.roles_display`) fonctionne aux deux
    endroits, la ou `queryset.values()` echouerait.

    **Les deux presentations disent alors le MEME mot pour la meme ligne**,
    la cellule de la liste et la carte du tableau lisant toutes deux cette
    propriete — et `column_of`, qui range la carte, se derive du meme
    champ. Un ecran qui se contredirait serait pire que pas de kanban."""

    @property
    def statut_operationnel(self) -> str:
        # Ce mixin est toujours melange a un `Model` — le cast dit a mypy ce
        # que la declaration de classe ne peut pas lui dire sans imposer une
        # base commune a des modeles de quatre modules.
        instance = cast(Any, self)
        board = board_for(instance._meta.label)
        if board is None:
            return ""
        # `get_FOO_display` n'existe que si le champ porte des `choices` ;
        # sans elles, le code brut reste la seule valeur disponible et vaut
        # mieux qu'une cellule vide.
        libelle = getattr(instance, f"get_{board.state_field}_display", None)
        if libelle is None:
            return str(getattr(instance, board.state_field, ""))
        return str(libelle())
