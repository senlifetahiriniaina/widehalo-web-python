"""Garde G-6 : un tableau declare doit savoir ce que dit sa carte.

**Ce qu'elle empeche.** Un document projete sur les cinq colonnes metier
s'ouvre en kanban PAR DEFAUT (C-4). Si son module ne declare pas les deux a
trois lignes de la carte, l'ecran le plus vu du module rend des cartes qui
ne portent que leur titre — et si la fiche n'est pas declaree, le clic
ouvre un popup vide. Les deux sont du decor, et le decor se refuse a la
declaration : `register_board` leve au demarrage.

**Et le defaut que cette garde-ci attrape, que `register_board` ne peut
pas voir.** Un attribut mal orthographie — `partner_dislay`, `amount_total`
au lieu de `amount_total_mga` — passe la declaration sans un mot :
`lire_lignes` lit par `getattr` avec un defaut, et la ligne s'affiche vide.
Aucune erreur, aucune trace, une carte muette. La verification ne peut se
faire qu'ici, une fois les modeles charges.

**L'instrument dit ce qui l'a convaincu** — regle inscrite dans 0.1.7 apres
six erreurs de mesure : il nomme le document, le groupe et l'attribut
fautif, et porte son auto-test (« vois-je encore des tableaux ? »).
"""

from __future__ import annotations

import pytest
from apps.core.services.presentation import (
    RESUME_MAX_LIGNES,
    RESUME_MIN_LIGNES,
    board_for,
    registered_boards,
)
from django.apps import apps as django_apps

#: Plancher de la mesure : les cinq documents des quatre modules
#: prioritaires. Liste INDEPENDANTE du registre — un jeu ferme ne se
#: verifie jamais contre sa propre source (lecon F60 de T6).
TABLEAUX_ATTENDUS = frozenset(
    {
        "sales.SalesOrder",
        "sales.SalesQuotation",
        "accounting.AccMove",
        "logistics.LogShipment",
        "logistics.LogTrip",
    }
)


def test_la_mesure_voit_encore_des_tableaux() -> None:
    """Auto-test : une garde qui ne mesure plus rien passe en silence."""
    declares = registered_boards()
    manquants = sorted(TABLEAUX_ATTENDUS - declares)
    assert not manquants, (
        f"Ces documents n'ont plus de tableau declare : {manquants}. "
        f"Registre courant : {sorted(declares)}."
    )


@pytest.mark.parametrize("model_label", sorted(registered_boards()))
def test_chaque_tableau_declare_une_carte_et_une_fiche_lisibles(model_label: str) -> None:
    board = board_for(model_label)
    assert board is not None

    assert RESUME_MIN_LIGNES <= len(board.resume) <= RESUME_MAX_LIGNES, (
        f"{model_label} declare {len(board.resume)} ligne(s) de carte : le commanditaire "
        f"en demande entre {RESUME_MIN_LIGNES} et {RESUME_MAX_LIGNES}."
    )
    assert board.fiche, f"{model_label} ouvrirait un popup vide : aucune fiche declaree."

    modele = django_apps.get_model(model_label)
    for groupe, lignes in (("carte", board.resume), ("fiche", board.fiche)):
        for ligne in lignes:
            assert hasattr(modele, ligne.attribut), (
                f"{model_label} declare, dans sa {groupe}, l'attribut « {ligne.attribut} » "
                f"que le modele ne porte pas : la ligne « {ligne.label} » s'afficherait vide, "
                f"sans la moindre erreur."
            )
            assert str(ligne.label), (
                f"{model_label} declare une ligne de {groupe} sans libelle "
                f"(attribut « {ligne.attribut} ») : la valeur s'afficherait sans dire ce "
                f"qu'elle est."
            )
