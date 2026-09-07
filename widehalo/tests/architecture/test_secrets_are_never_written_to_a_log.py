"""Garde-fou bloquant — FLX-8 : la rédaction est appelée là où elle doit
l'être, et son vocabulaire ne diverge pas de celui du chiffrement.

Le critère : « un motif ressemblant à un secret n'apparaît dans aucun
journal, aucune charge utile archivée et aucun message d'erreur affiché à
l'utilisateur. »

**Ce que cette garde ajoute à celle du chiffrement.**
`test_secrets_are_never_stored_in_clear.py` est une introspection de
MODÈLES : elle vérifie la forme des colonnes, et ne regarde jamais un
journal, une trace, un message d'API ou une charge utile. Les deux gardes
sont complémentaires et aucune ne remplace l'autre — un secret peut être
parfaitement chiffré en base et parfaitement lisible dans un journal.

**Pourquoi une garde structurelle en plus des tests de comportement.** Les
tests de `apps/flows/tests/test_s6_flx8_redaction.py` vérifient les chemins
qui existent aujourd'hui. Celle-ci verrouille les POINTS D'ÉCRITURE : le
jour où quelqu'un ajoute une colonne de message, ou déplace l'écriture
ailleurs, un test de comportement ne dira rien tant que personne n'aura
écrit le test correspondant. La garde, elle, se plaindra tout de suite.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from apps.core.services.redaction import NOMS_DE_SECRET

from tests.architecture._ast_utils import APPS_DIR

#: `tests/architecture/` vit sous `widehalo/`, comme `apps/` : deux
#: remontées suffisent, une troisième sortirait du projet Django.
PROJET = Path(__file__).resolve().parent.parent.parent

#: Les fonctions qui ÉCRIVENT une des trois surfaces, et le fichier où
#: elles vivent. Chacune doit appeler la rédaction dans son propre corps —
#: pas dans celui d'un appelant, qui peut être remplacé.
POINTS_D_ECRITURE = {
    ("apps/flows/services/exchange.py", "prepare_exchange"): (
        "Écrit `FlwPayload.body` : la surface « charge utile archivée ». Le "
        "cahier l'exige à l'écriture (§13.2), et l'empreinte se calcule sur "
        "le corps rédigé — l'inverse prouverait un contenu jamais transmis."
    ),
    ("apps/flows/services/exchange.py", "transition_exchange"): (
        "Écrit `FlwExchange.result_message` : la surface « message affiché à "
        "l'utilisateur ». Seul point d'écriture de la colonne — rédiger chez "
        "les appelants laisserait le prochain appelant rouvrir la fuite."
    ),
    ("apps/flows/services/incidents.py", "record_failure"): (
        "Écrit `FlwIncident.last_result_message`, ce que l'exploitation "
        "regarde en premier. Recopie ce que le tiers renvoie, et un tiers qui "
        "refuse une authentification renvoie volontiers l'en-tête reçu."
    ),
}


def _fonction(chemin: str, nom: str) -> ast.FunctionDef:
    arbre = ast.parse((PROJET / chemin).read_text(encoding="utf-8"))
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.FunctionDef) and noeud.name == nom:
            return noeud
    raise AssertionError(f"{nom} introuvable dans {chemin} — la garde ne garde plus rien.")


def appelle_la_redaction(noeud: ast.AST) -> bool:
    """`True` si ce sous-arbre appelle `redact_secrets`, sous l'une ou
    l'autre de ses formes d'appel."""
    for interne in ast.walk(noeud):
        if not isinstance(interne, ast.Call):
            continue
        cible = interne.func
        if isinstance(cible, ast.Name) and cible.id == "redact_secrets":
            return True
        if isinstance(cible, ast.Attribute) and cible.attr == "redact_secrets":
            return True
    return False


@pytest.mark.parametrize("cle,motif", sorted(POINTS_D_ECRITURE.items()))
def test_every_write_point_redacts(cle: tuple[str, str], motif: str) -> None:
    chemin, nom = cle
    assert appelle_la_redaction(_fonction(chemin, nom)), (
        f"{chemin}::{nom} n'appelle plus `redact_secrets`. {motif}"
    )


@pytest.mark.parametrize("cle,motif", sorted(POINTS_D_ECRITURE.items()))
def test_every_write_point_says_why_it_is_one(cle: tuple[str, str], motif: str) -> None:
    """Une entrée de registre sans motif écrit n'est pas une décision,
    c'est une case cochée. Même seuil que les autres gardes du dépôt."""
    assert len(motif) >= 40, f"{cle} : motif trop court."


def test_the_detector_sees_a_call_and_only_a_call() -> None:
    """Auto-test. Une garde qui ne détecte rien reste verte pour toujours —
    ce dépôt le vérifie partout, et il n'y a pas de raison d'en dispenser
    celle-ci."""
    avec = ast.parse("def f(x):\n    return redact_secrets(x)")
    avec_attribut = ast.parse("def f(x):\n    return redaction.redact_secrets(x)")
    sans = ast.parse("def f(x):\n    return x.upper()")
    faux_ami = ast.parse("def f(x):\n    redact_secrets\n    return x")
    assert appelle_la_redaction(avec) is True
    assert appelle_la_redaction(avec_attribut) is True
    assert appelle_la_redaction(sans) is False
    assert appelle_la_redaction(faux_ami) is False, (
        "Nommer la fonction sans l'appeler ne rédige rien : un détecteur qui "
        "se contenterait du nom serait satisfait par un import inutilisé."
    )


def test_the_redaction_vocabulary_covers_the_storage_one() -> None:
    """**Le point que le dépôt paie ailleurs quand il l'oublie.**
    `object_remap.SECRET_TOKEN_FIELD_NAMES` a déjà cessé, en silence, de
    couvrir ce qu'il devait couvrir le jour où un champ `token` a été
    renommé `token_hash` — c'est écrit dans sa propre docstring. Deux
    vocabulaires de secret qui divergent produisent exactement cela : une
    garde qui protège encore, mais plus la même chose.

    Le vocabulaire du rédacteur doit donc contenir celui de la garde de
    chiffrement, qui est la liste de référence du dépôt. Il peut être plus
    large — `authorization`, `signature`, `client_secret` n'apparaissent
    que dans une trace HTTP, jamais comme nom de colonne — mais jamais plus
    étroit."""
    import re

    from tests.architecture.test_secrets_are_never_stored_in_clear import _SECRET_NAME

    # Les noms que la garde de stockage reconnaît, extraits de son
    # expression plutôt que recopiés : recopier, c'est précisément ce qui
    # fait diverger deux vocabulaires.
    groupe = re.search(r"\(([a-z_|]+)\)\(_hash\)", _SECRET_NAME.pattern)
    assert groupe, "L'expression de la garde de stockage a changé de forme."
    noms_du_stockage = set(groupe.group(1).split("|"))

    manquants = noms_du_stockage - set(NOMS_DE_SECRET)
    assert manquants == set(), (
        f"Le rédacteur ignore des noms que la garde de stockage reconnaît : {manquants}. "
        "Un secret chiffré en base et lisible dans un journal reste un secret fuité."
    )


def test_no_module_defines_a_second_redactor() -> None:
    """Un second rédacteur, c'est un second vocabulaire, et donc à terme
    deux protections qui ne protègent plus la même chose. Il n'y en a
    qu'un, et il vit dans `core` parce que le formateur de journalisation
    est global et que `core` ne peut pas importer un module métier."""
    doublons = []
    for chemin in APPS_DIR.rglob("*.py"):
        if "/tests/" in str(chemin) or chemin.name.startswith("test_"):
            continue
        if chemin.name == "redaction.py" and chemin.parent.name == "services":
            continue
        arbre = ast.parse(chemin.read_text(encoding="utf-8"), filename=str(chemin))
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.FunctionDef) and noeud.name in {
                "redact_secrets",
                "mask_secrets",
                "sanitize_secrets",
            }:
                doublons.append(f"{chemin.relative_to(APPS_DIR)}::{noeud.name}")
    assert doublons == [], f"Second rédacteur défini : {doublons}"
