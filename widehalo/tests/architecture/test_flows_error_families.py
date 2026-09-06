"""Garde-fou bloquant — le jeu d'erreurs du hub reste FERMÉ à six familles.

Le cahier ne laisse pas de marge : « Chaque adaptateur doit donc traduire
les erreurs du tiers dans un jeu fermé de six familles, chacune associée à
une action de reprise unique et compréhensible [...] Un adaptateur qui
remonte une septième famille ne passe pas la recette » (§10.3).

**Pourquoi une garde plutôt qu'une relecture.** Le motif de dérive est
connu et documenté dans ce dépôt : une énumération qu'on peut allonger sans
que rien ne proteste redevient du texte libre en deux sprints. Le premier
adaptateur réel rencontrera une erreur qui « n'entre dans aucune des six »
et la tentation sera d'en ajouter une septième plutôt que de choisir. C'est
exactement ce que le cahier interdit, et pour une raison de produit : le
tableau des reprises est ce qui rend la console lisible par un comptable, et
il cesse de l'être dès qu'il compte douze lignes.

Le plafond ne peut être relevé que par une décision explicite du
commanditaire, comme les budgets de modèles, d'écrans et d'adaptateurs.
"""

from __future__ import annotations

from apps.flows.models import FlwIncident
from apps.flows.services.incidents import RECOVERY_ACTIONS

#: Les six familles de §10.3, recopiées ICI depuis le cahier et non
#: importées du modèle. C'est délibéré : un test qui lirait l'énumération
#: qu'il vérifie serait vert quel que soit son contenu. La duplication est
#: le mécanisme, pas un oubli.
FAMILLES_DU_CAHIER = {
    "identifiants",
    "donnee_invalide",
    "refus_tiers",
    "tiers_indisponible",
    "plafond_atteint",
    "anomalie_editeur",
}


def test_the_error_family_set_is_exactly_the_one_the_cahier_closes() -> None:
    livrees = {code for code, _label in FlwIncident.FAMILY_CHOICES}
    assert livrees == FAMILLES_DU_CAHIER, (
        "Le jeu de familles d'erreur a changé.\n"
        f"En trop : {sorted(livrees - FAMILLES_DU_CAHIER)}\n"
        f"Manquantes : {sorted(FAMILLES_DU_CAHIER - livrees)}\n"
        "Le cahier (§10.3) ferme ce jeu à six : « un adaptateur qui remonte une "
        "septième famille ne passe pas la recette ». Une erreur qui n'entre dans "
        "aucune des six se RANGE dans « anomalie à signaler à l'éditeur » — c'est "
        "précisément à quoi cette famille sert. En ajouter une demande une décision "
        "explicite du commanditaire, au même titre qu'un relèvement de budget."
    )


def test_every_family_carries_a_recovery_action() -> None:
    """Une famille sans action de reprise afficherait, dans la console, un
    incident qui ne dit pas quoi faire — l'inutilisabilité que §10.3
    cherche justement à éviter."""
    assert set(RECOVERY_ACTIONS) == FAMILLES_DU_CAHIER, (
        f"Familles sans reprise : {sorted(FAMILLES_DU_CAHIER - set(RECOVERY_ACTIONS))} ; "
        f"reprises orphelines : {sorted(set(RECOVERY_ACTIONS) - FAMILLES_DU_CAHIER)}."
    )


def test_no_recovery_action_merely_restates_the_error() -> None:
    """§10.3 exige une ACTION de reprise, pas une reformulation du symptôme.
    « Le tiers a renvoyé 401 » n'est pas une action ; « renouveler les
    identifiants » en est une.

    La vérification est grossière — la longueur et la présence d'un verbe
    d'action — et c'est assumé : elle n'attrape pas une mauvaise phrase,
    elle attrape une phrase VIDE, c'est-à-dire le cas où quelqu'un ajoute
    une famille et remplit son action d'un mot pour faire passer le test
    précédent."""
    verbes = (
        "renouveler",
        "corriger",
        "lire",
        "relever",
        "signaler",
        "aucune action",
        "basculer",
    )
    for famille, action in RECOVERY_ACTIONS.items():
        texte = str(action).lower()
        assert len(texte) >= 40, f"Action de reprise trop courte pour {famille!r} : {texte!r}"
        assert any(verbe in texte for verbe in verbes), (
            f"L'action de reprise de {famille!r} ne dit pas quoi FAIRE : {texte!r}"
        )
