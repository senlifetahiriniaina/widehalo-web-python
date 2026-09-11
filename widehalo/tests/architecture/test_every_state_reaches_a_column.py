"""Garde C-4 : un etat non projete fait disparaitre ses lignes.

**Ce qu'elle empeche.** Le kanban groupe les cartes par colonne metier, et
les listes d'operations affichent cette meme colonne. Un etat ajoute
demain sans entree dans la table de projection ne leverait rien : ses
lignes n'appartiendraient simplement a aucune colonne, et
disparaitraient de l'ecran. Un document invisible est pire qu'un document
mal range — c'est la variante « donnee » du motif des ecrans
inatteignables que T10 a ferme.

**Le jeu ferme est verifie contre une source INDEPENDANTE** (lecon F60 de
T6) : les etats reels sont relus dans les `choices` du champ, jamais dans
la table de projection que la garde surveille. Une table qui se
verifierait contre elle-meme passerait toujours.

Elle verifie les deux sens : aucun etat reel oublie, et aucun etat projete
qui n'existe plus — sans quoi un etat supprime laisserait une entree morte
que personne ne retirerait.
"""

from __future__ import annotations

import pytest
from apps.core.services.presentation import board_for, registered_boards
from django.apps import apps as django_apps

#: Les documents d'operations des quatre modules prioritaires. `crm.CrmLead`
#: n'y figure PAS, et c'est delibere : ses colonnes sont ses `CrmStage`, un
#: pipeline configurable par societe (CRM-4). Le projeter sur cinq colonnes
#: fixes effacerait ce que le client a configure.
DOCUMENTS_ATTENDUS = frozenset(
    {
        "sales.SalesOrder",
        "sales.SalesQuotation",
        "accounting.AccMove",
        "logistics.LogShipment",
        "logistics.LogTrip",
    }
)


def test_the_measurement_still_finds_boards() -> None:
    """Un registre vide declarerait tout sain.

    C'est la panne silencieuse de cette famille de gardes, rencontree
    quatre fois dans cette vague."""
    assert registered_boards(), (
        "Aucune projection enregistree : les modules ne les declarent plus depuis "
        "`apps.py::ready()`, et le kanban comme la colonne de statut seraient vides."
    )


def test_every_operations_document_declares_a_board() -> None:
    manquants = sorted(DOCUMENTS_ATTENDUS - registered_boards())
    assert not manquants, (
        f"Ces documents d'operations n'ont plus de projection : {manquants}. "
        f"Leurs lignes n'appartiendraient a aucune colonne."
    )


@pytest.mark.parametrize("label", sorted(DOCUMENTS_ATTENDUS))
def test_every_real_state_reaches_a_column(label: str) -> None:
    """Chaque etat declare par le MODELE est projete sur une colonne."""
    board = board_for(label)
    assert board is not None, f"{label} n'a pas de projection."
    modele = django_apps.get_model(*label.split("."))
    reels = {
        valeur for valeur, _libelle in (modele._meta.get_field(board.state_field).choices or [])
    }
    assert reels, f"{label}.{board.state_field} ne declare aucun `choices` : la mesure est vide."

    non_projetes = sorted(reels - set(board.par_etat))
    assert not non_projetes, (
        f"{label} : ces etats ne sont projetes sur aucune colonne : {non_projetes}. "
        f"Les lignes qui les portent disparaitraient du kanban ET de la colonne "
        f"« Statut » des listes, sans erreur."
    )


@pytest.mark.parametrize("label", sorted(DOCUMENTS_ATTENDUS))
def test_no_projection_points_at_a_vanished_state(label: str) -> None:
    """L'autre sens : une entree qui ne designe plus aucun etat est morte.

    Sans cette moitie, un etat renomme laisserait son ancienne entree dans
    la table, et personne ne saurait qu'elle ne sert plus."""
    board = board_for(label)
    assert board is not None
    modele = django_apps.get_model(*label.split("."))
    reels = {
        valeur for valeur, _libelle in (modele._meta.get_field(board.state_field).choices or [])
    }
    fantomes = sorted(set(board.par_etat) - reels)
    assert not fantomes, (
        f"{label} : ces etats projetes n'existent plus dans le modele : {fantomes}. "
        f"Entrees mortes a retirer de la table de projection."
    )
