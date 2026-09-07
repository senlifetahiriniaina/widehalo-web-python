"""Garde-fou bloquant — le jeu de transformations reste FERMÉ à six.

Le cahier ne laisse pas de marge (axe A2) : « Association un pour un entre
champ source et champ cible, avec un jeu fermé de transformations : format
de date, séparateur décimal, casse, concaténation, valeur constante, table
de correspondance de valeurs. »

**Même discipline que les six familles d'erreur de S3, et pour la même
raison.** Une énumération qu'on peut allonger sans que rien ne proteste
redevient du texte libre en deux sprints. Le premier connecteur réel
rencontrera une valeur qui « n'entre dans aucune des six » et la tentation
sera d'ajouter une septième transformation plutôt que de composer avec les
six. Le plafond ne peut être relevé que par une décision explicite du
commanditaire, comme les budgets de modèles, d'écrans et d'adaptateurs.

**La seconde garde est celle qui aurait manqué.** Une transformation
DÉCLARÉE mais non IMPLÉMENTÉE passerait la validation à l'enregistrement,
puis exploserait au premier envoi chez le tiers — précisément ce que FLX-6
existe pour empêcher (« plutôt que d'échouer au premier envoi »). Les deux
jeux doivent donc être exactement égaux, dans les deux sens.
"""

from __future__ import annotations

import pytest
from apps.flows.services.mapping import (
    KNOWN_TRANSFORMS,
    MULTI_SOURCE_TRANSFORMS,
    REQUIRED_PARAMETERS,
    TRANSFORM_CHOICES,
    TRANSFORMERS,
)

#: Les six de l'axe A2, recopiées ICI depuis le cahier et non importées du
#: service. C'est délibéré : un test qui lirait l'énumération qu'il vérifie
#: serait vert quel que soit son contenu. La duplication est le mécanisme,
#: pas un oubli.
TRANSFORMATIONS_DU_CAHIER = {
    "format_date",
    "separateur_decimal",
    "casse",
    "concatenation",
    "valeur_constante",
    "table_de_correspondance",
}


def test_the_transformation_set_is_exactly_the_one_the_cahier_closes() -> None:
    assert KNOWN_TRANSFORMS == TRANSFORMATIONS_DU_CAHIER, (
        "Le jeu de transformations a bougé. L'axe A2 le ferme à six ; le "
        "relever est une décision du commanditaire, pas un ajustement de "
        f"sprint. Manquantes : {TRANSFORMATIONS_DU_CAHIER - KNOWN_TRANSFORMS} ; "
        f"en trop : {KNOWN_TRANSFORMS - TRANSFORMATIONS_DU_CAHIER}."
    )


def test_every_declared_transformation_has_an_implementation() -> None:
    """Le sens qui compte le plus : déclarer sans implémenter produit une
    correspondance acceptée à l'enregistrement et fatale au premier envoi."""
    assert set(TRANSFORMERS) == KNOWN_TRANSFORMS, (
        f"Déclarées sans implémentation : {KNOWN_TRANSFORMS - set(TRANSFORMERS)} ; "
        f"implémentées sans déclaration : {set(TRANSFORMERS) - KNOWN_TRANSFORMS}."
    )


def test_every_transformation_is_offered_to_the_user() -> None:
    """Une transformation qui n'apparaît pas dans les choix n'existe que
    pour le code — l'éditeur de correspondance ne peut pas la proposer."""
    assert {code for code, _label in TRANSFORM_CHOICES} == KNOWN_TRANSFORMS


def test_every_transformation_declares_its_required_parameters() -> None:
    """Même une transformation sans paramètre doit figurer dans la table,
    avec un tuple vide. L'absence d'entrée et « aucun paramètre requis »
    sont indiscernables à la lecture du dictionnaire, et
    `REQUIRED_PARAMETERS.get(...)` les traiterait pareil — ce qui rendrait
    un oubli invisible."""
    assert set(REQUIRED_PARAMETERS) == KNOWN_TRANSFORMS


def test_only_concatenation_takes_several_sources() -> None:
    """L'arbitrage écrit dans la docstring du service, rendu opposable.

    L'axe A2 se contredit : il annonce une association « un pour un » puis
    inclut la concaténation, qui est plusieurs-vers-un. Le critère l'emporte
    sur la prose — la concaténation est donc supportée, et elle est la
    SEULE exception."""
    assert {"concatenation"} == MULTI_SOURCE_TRANSFORMS


@pytest.mark.parametrize("code", sorted(TRANSFORMATIONS_DU_CAHIER))
def test_each_transformation_is_named_in_french_snake_case(code: str) -> None:
    """Cohérence avec les six familles d'erreur de S3 (`donnee_invalide`,
    `tiers_indisponible`…). Un jeu fermé moitié anglais moitié français
    finit par en devenir deux."""
    assert code == code.lower()
    assert " " not in code and "-" not in code
