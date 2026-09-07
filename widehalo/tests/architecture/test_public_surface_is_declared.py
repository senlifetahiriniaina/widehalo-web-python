"""Garde-fou bloquant — API-2 : la surface publique est DÉCLARÉE, et rien
d'autre n'y est atteignable.

Le critère : « aucune opération non déclarée dans la liste blanche publique
n'est atteignable par un jeton client, même si l'endpoint interne existe. »

**Deux façons de le tenir, et une seule survit à la relecture.** On peut
appeler les contrôles à la main dans chaque vue publique — et la première
vue ajoutée sans eux sera ouverte à toute clé, en silence, sans qu'aucun
test existant ne rougisse. Ou on peut EXIGER que chaque route publique porte
son décorateur, et vérifier ici que c'est le cas. La seconde rend le critère
structurel plutôt que mémorisé, ce qui est exactement la différence entre
`endpoint_governance.py` et une convention.

**La correspondance doit tenir dans les DEUX SENS.** Une route sans
opération déclarée est une porte ouverte ; une opération déclarée que
personne ne sert est un engagement de rétrocompatibilité pris sur du vide —
et il compte dans le plafond de 80.

**Ce que cette garde ne fait pas.** Elle ne vérifie pas que chaque opération
publique respecte les droits de son porteur : c'est un comportement, testé
là où il vit (`apps/flows/tests/test_s7_public_api_keys.py`). Elle vérifie
la STRUCTURE — que le mécanisme est branché partout — et rien d'autre.
"""

from __future__ import annotations

import pytest
from apps.flows.public_operations import list_public_operations, public_operation_codes
from django.conf import settings


def _routes_publiques() -> list[tuple[str, str, object]]:
    """(méthode, chemin, vue) pour chaque opération montée sur l'API
    publique."""
    from config.api_public import public_api

    routes = []
    for prefixe, router in public_api._routers:
        for chemin, path_view in router.path_operations.items():
            for operation in path_view.operations:
                for methode in operation.methods:
                    routes.append((methode, f"{prefixe}{chemin}", operation.view_func))
    return routes


def _code_de(vue: object) -> str | None:
    return getattr(vue, "public_operation_code", None)


def test_the_public_surface_is_not_empty() -> None:
    """Une garde qui ne scrute rien reste verte pour toujours. Le seuil est
    à un : il dit « la surface existe », pas « elle a la bonne taille »."""
    assert _routes_publiques(), "Aucune route publique montée : la garde ne garderait rien."
    assert public_operation_codes(), "Aucune opération publique déclarée."


def test_every_public_route_declares_the_operation_it_serves() -> None:
    """Le sens qui compte : une route publique sans opération déclarée est
    atteignable par n'importe quelle clé, quelle que soit sa portée."""
    nues = [
        f"{methode} {chemin}"
        for methode, chemin, vue in _routes_publiques()
        if _code_de(vue) is None
    ]
    assert nues == [], (
        f"Route(s) publique(s) sans décorateur `@public_operation` : {nues}. "
        "Elles seraient ouvertes à toute clé, quelle que soit sa portée."
    )


def test_every_route_names_a_registered_operation() -> None:
    """Un code décoré mais jamais enregistré ne serait dans la portée
    d'aucune clé : la route serait morte, et son message d'erreur
    incompréhensible."""
    connues = public_operation_codes()
    fantomes = {
        _code_de(vue) for _m, _c, vue in _routes_publiques() if _code_de(vue) not in connues
    }
    fantomes.discard(None)
    assert fantomes == set(), f"Opération(s) décorée(s) mais non déclarée(s) : {fantomes}."


def test_every_declared_operation_is_actually_served() -> None:
    """L'autre sens. Une opération déclarée que personne ne sert est un
    engagement de rétrocompatibilité pris sur du vide — et elle consomme
    une place du plafond de 80."""
    servies = {_code_de(vue) for _m, _c, vue in _routes_publiques()}
    orphelines = public_operation_codes() - servies
    assert orphelines == set(), (
        f"Opération(s) déclarée(s) que rien ne sert : {orphelines}. Une opération "
        "publiée ne se retire plus ; en déclarer une sans la servir engage la "
        "rétrocompatibilité sur du vide."
    )


def test_no_internal_router_is_mounted_on_the_public_surface() -> None:
    """« Même si l'endpoint interne existe. » Monter un routeur interne ici
    publierait d'un coup des dizaines d'opérations, sans décision et sans
    passer par le plafond."""
    from config.api import api
    from config.api_public import public_api

    interne = {id(router) for _prefix, router in api._routers}
    publics = {id(router) for _prefix, router in public_api._routers}
    assert interne & publics == set(), (
        "Un routeur est monté sur les DEUX surfaces : la surface publique "
        "hériterait de tout ce que l'interne ajoute, sans décision."
    )


@pytest.mark.parametrize("operation", list_public_operations())
def test_every_operation_declares_a_permission_and_a_label(operation) -> None:
    """Une opération sans permission serait ouverte à tout porteur de clé —
    c'est-à-dire une élévation de droits par l'API, ce qu'API-1 interdit.
    Une opération sans libellé n'est pas documentable."""
    assert operation.permission, f"{operation.code} n'exige aucune permission."
    assert "." in operation.permission, (
        f"{operation.code} : la permission doit être un codename Django complet "
        f"(`app.verbe_modele`), pas « {operation.permission} »."
    )
    assert operation.label
    assert operation.description, (
        f"{operation.code} n'a pas de description : elle sera publiée telle "
        "quelle dans l'OpenAPI public, où un intégrateur la lira sans nous."
    )


def test_the_public_budget_leaves_room_and_is_measured() -> None:
    """Le plafond est vérifié par `test_phase4_budgets.py` ; ici on vérifie
    qu'il n'est pas déjà saturé sans que personne ne l'ait remarqué — un
    plafond atteint doit être une DÉCISION, pas une surprise au moment
    d'ajouter la suivante."""
    compte = len(public_operation_codes())
    assert compte <= settings.BUDGET_MAX_PUBLIC_OPERATIONS
    assert compte < settings.BUDGET_MAX_PUBLIC_OPERATIONS, (
        "Le plafond d'opérations publiques est ATTEINT. Le relever est une "
        "décision du commanditaire, comme les budgets de modèles et d'écrans."
    )


def test_the_detector_would_see_an_undecorated_route() -> None:
    """Auto-test. Sans lui, un `_code_de` qui renverrait toujours un code
    laisserait la garde verte quoi qu'il arrive."""

    def vue_nue(request):  # pragma: no cover - jamais appelée
        return None

    from apps.flows.api_public import public_operation

    assert _code_de(vue_nue) is None
    assert _code_de(public_operation("x.y")(vue_nue)) == "x.y"
