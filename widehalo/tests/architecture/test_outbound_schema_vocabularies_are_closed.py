"""Garde-fou bloquant — T0 : les deux vocabulaires que le couplage empeche
de partager restent identiques.

`apps.core` ne peut pas importer `apps.flows` (regle de couplage n°1,
`test_module_boundaries.py`). Deux vocabularies vivent donc en double :

1. les huit operations OP1-OP8, definies dans `apps.flows.operations` et
   RECOPIEES dans `apps.core.services.outbound_schemas.OPERATION_CODES`
   pour que les modules metier puissent declarer quelle operation exige
   quel champ sans importer le hub ;
2. le jeu ferme d'operateurs de filtre, dont chaque code doit avoir une
   implementation — meme discipline que `KNOWN_TRANSFORMS`/`TRANSFORMERS`
   de S5, et pour la meme raison : un operateur declare sans
   implementation serait accepte a l'enregistrement puis exploserait au
   premier evenement.

Ce fichier est le seul endroit qui voit les deux cotes. Sans lui, la
recopie derive silencieusement — et une portee « OP9 » serait declarable
par un module metier sans que rien ne proteste.
"""

from __future__ import annotations

from apps.core.services.outbound_schemas import (
    OPERATION_CODES as OPERATIONS_RECOPIEES,
)
from apps.core.services.outbound_schemas import (
    list_outbound_documents,
)
from apps.flows.operations import OPERATION_CODES as OPERATIONS_DU_HUB
from apps.flows.services.triggers import FILTER_OPERATORS, KNOWN_FILTER_OPERATORS


def test_the_copied_operation_vocabulary_still_matches_the_hub() -> None:
    assert OPERATIONS_RECOPIEES == OPERATIONS_DU_HUB, (
        "La recopie des operations dans `core.services.outbound_schemas` a "
        "derive par rapport a `flows.operations`. Les modules metier "
        "declareraient des exigences sur des operations qui n'existent plus."
    )


def test_every_declared_operation_requirement_names_a_real_operation() -> None:
    """Un champ exige par « OP9 » ne serait exige par rien.

    Le registre le refuse deja a la declaration ; ce test le verifie sur
    les declarations REELLES, celles chargees par `apps.py::ready()` —
    c'est-a-dire sur ce qui tourne, pas sur un cas construit."""
    for document in list_outbound_documents():
        for champ in document.fields:
            inconnues = set(champ.required_by) - OPERATIONS_DU_HUB
            assert not inconnues, f"{document.code}.{champ.path} : operations inconnues {inconnues}"


def test_every_filter_operator_has_an_implementation() -> None:
    assert frozenset(FILTER_OPERATORS) == KNOWN_FILTER_OPERATORS, (
        "Un operateur de filtre declare sans implementation serait accepte a "
        "l'enregistrement puis exploserait au premier evenement."
    )
