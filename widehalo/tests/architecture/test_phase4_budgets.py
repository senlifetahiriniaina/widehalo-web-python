"""Garde-fou bloquant — les deux budgets NOUVEAUX de la Phase 4 (cahier
§11.1), poses au sprint S1 du bloc A.

Ils ne remplacent pas les trois plafonds de `test_budget.py` : ils bornent
deux surfaces que les compteurs globaux ne voient pas.

**ADAPTATEURS (12).** Le cahier en fait « le plus important de la phase » :
« un catalogue de connecteurs derive exactement comme un catalogue de
rapports ou une table de rubriques : chaque client apporte son cas
particulier, personne ne retire jamais rien, et au bout de deux ans
l'entretien consomme toute la capacite. Le plafond force a repondre par
l'API publique plutot que par un adaptateur de plus. »

Ce garde-fou compte les adaptateurs REELLEMENT IMPLEMENTES — les modules
`apps/flows/adapters/*.py` — et non les lignes `FlwConnector` en base. La
distinction est le coeur du sujet : ce qui coute a entretenir, c'est du
code, pas une ligne de configuration. Compter les lignes en base ferait
d'ailleurs dependre un plafond d'architecture de donnees de production, ce
qui n'a pas de sens en integration continue.

**OPERATIONS PUBLIQUES (80).** Surface exposee aux tiers, plafonnee
SEPAREMENT des endpoints internes « parce qu'elle a un cout de
retrocompatibilite que les endpoints internes n'ont pas : une operation
publiee ne se retire plus, elle se deprecie sur plusieurs versions ». La
diluer dans les 1 500 endpoints internes reviendrait a ne pas la borner.

**Etat au sprint S1 : les deux compteurs sont a zero, et c'est normal.**
Aucun adaptateur n'est ecrit (bloc A, S6 en livrera un factice), aucune
operation publique n'est exposee (bloc B, S7-S9). Un test qui ne compte
rien serait vert par construction — c'est precisement ce que ce projet
appelle un theatre de securite. D'ou les tests d'AMORCAGE ci-dessous : ils
verifient que le compteur sait compter, en lui presentant une arborescence
factice, plutot que de se contenter d'un zero rassurant.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ADAPTERS_DIR = REPO_ROOT / "apps" / "flows" / "adapters"


def _count_adapters(adapters_dir: Path = ADAPTERS_DIR) -> list[str]:
    """Adaptateurs implementes : un module Python par adaptateur.

    `__init__.py` et les modules prefixes par `_` sont exclus : le premier
    n'est pas un adaptateur, les seconds sont des utilitaires partages
    (patron `_accent_utils.py`, `_ast_utils.py` deja employe ailleurs)."""
    if not adapters_dir.exists():
        return []
    return sorted(
        path.stem
        for path in adapters_dir.glob("*.py")
        if path.stem != "__init__" and not path.stem.startswith("_")
    )


def _count_public_operations() -> int:
    """Operations de l'API PUBLIQUE, distinguees des endpoints internes.

    La surface publique n'existe pas encore (bloc B). Quand elle existera,
    elle sera montee sous son propre routeur versionne et ce compteur lira
    ce routeur — jamais l'ensemble de `config.api`, qui melange l'interne
    et le public et ferait donc echouer le plafond public pour des raisons
    internes.

    Renvoie 0 tant que le routeur n'existe pas, ce que
    `test_the_public_surface_is_not_yet_open` documente explicitement pour
    qu'un zero ne passe jamais pour une mesure."""
    try:
        from config.api_public import public_api  # type: ignore[import-not-found]
    except ImportError:
        return 0
    count = 0
    for _prefix, router in public_api._routers:
        for path_view in router.path_operations.values():
            count += len(path_view.operations)
    return count


def test_adapter_budget_not_exceeded() -> None:
    adapters = _count_adapters()
    assert len(adapters) <= settings.BUDGET_MAX_ADAPTERS, (
        f"Plafond d'adaptateurs depasse : {len(adapters)}/"
        f"{settings.BUDGET_MAX_ADAPTERS}.\n{adapters}\n"
        "Le cahier tranche ce cas a l'avance : au-dela du plafond, la reponse est "
        "l'API PUBLIQUE, pas un adaptateur de plus — y compris pour un client "
        "important. Relever ce plafond demande une decision explicite du "
        "commanditaire, comme pour les budgets de modeles/endpoints/ecrans."
    )


def test_public_operations_budget_not_exceeded() -> None:
    count = _count_public_operations()
    assert count <= settings.BUDGET_MAX_PUBLIC_OPERATIONS, (
        f"Plafond d'operations publiques depasse : {count}/"
        f"{settings.BUDGET_MAX_PUBLIC_OPERATIONS}. Une operation publiee ne se "
        "retire plus, elle se deprecie sur plusieurs versions : ce plafond borne "
        "un engagement de retrocompatibilite, pas une quantite de code."
    )


def test_the_adapter_counter_actually_counts(tmp_path: Path) -> None:
    """Auto-test du compteur d'adaptateurs.

    Au sprint S1 le compte reel est ZERO : sans ce test, `_count_adapters`
    pourrait renvoyer une liste vide pour une raison quelconque (mauvais
    chemin, mauvaise extension) et le plafond resterait vert pour
    toujours — y compris le jour ou vingt adaptateurs existeront.

    On lui presente donc une arborescence factice et on verifie qu'il voit
    les vrais adaptateurs, et seulement eux."""
    fake = tmp_path / "adapters"
    fake.mkdir()
    for name in ("__init__.py", "_shared.py", "fiscal_dgi.py", "paiement_agregateur.py"):
        (fake / name).write_text("", encoding="utf-8")
    (fake / "notes.txt").write_text("", encoding="utf-8")

    assert _count_adapters(fake) == ["fiscal_dgi", "paiement_agregateur"], (
        "Le compteur d'adaptateurs ne compte pas ce qu'il devrait : le plafond "
        "des douze serait vert quel que soit le nombre reel d'adaptateurs."
    )


def test_the_adapter_counter_survives_a_missing_directory() -> None:
    """`apps/flows/adapters/` n'existe pas encore (S6 le creera). Le
    compteur doit renvoyer une liste vide, jamais lever : une garde qui
    plante est une garde qu'on finit par desactiver."""
    assert _count_adapters(REPO_ROOT / "apps" / "flows" / "n_existe_pas") == []


def test_the_public_surface_is_open_and_counted() -> None:
    """Remplace le test d'amorcage de S1 (« la surface publique n'est pas
    encore ouverte »), qui portait dans son propre corps l'instruction de le
    retirer ici. Elle est ouverte depuis le sprint S7, et ce test verifie ce
    que celui-la demandait de verifier en partant : que le compteur lise
    bien le ROUTEUR PUBLIC versionne, et non `config.api`.

    La distinction est tout l'objet du plafond : `config.api` melange
    l'interne et le public, et le compter ferait echouer un plafond de
    retrocompatibilite pour des raisons internes."""
    compte = _count_public_operations()
    assert compte >= 1, (
        "Le compteur d'operations publiques rend zero alors que la surface "
        "existe : il ne lit pas `config.api_public`."
    )
    assert compte < len(_all_internal_operations()), (
        "Le compteur d'operations publiques compte AUSSI la surface interne : "
        "les deux plafonds seraient alors indissociables."
    )


def _all_internal_operations() -> list[str]:
    """Les operations de la surface INTERNE, pour le temoin ci-dessus."""
    from config.api import api

    return [
        f"{methode}:{chemin}"
        for _prefix, router in api._routers
        for chemin, path_view in router.path_operations.items()
        for operation in path_view.operations
        for methode in operation.methods
    ]
