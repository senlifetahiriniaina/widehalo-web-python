"""Garde-fou bloquant — tout événement publié en production nomme sa société.

**Ce n'est pas une règle de style, c'est la condition pour qu'un flux
d'automatisation existe.** `apps/automation/services/dispatch.py` sort
immédiatement quand `tenant_id` est absent, avec un commentaire qui explique
correctement pourquoi : tout `AutoFlow` appartient à une société
(`BaseModel`), donc un événement sans société ne peut en désigner aucun.
Conséquence mécanique : **un `publish_event` sans `tenant_id` est un
événement journalisé que rien ne peut écouter.**

**Le défaut que cette garde ferme.** `apps/core/workflows.py` — le publieur
le plus général du dépôt, celui qui voit passer TOUTE transition FSM de
TOUT modèle — était le seul des vingt-six à ne pas renseigner la société.
Aucun `AutoFlow` branché sur une transition de workflow ne pouvait donc se
déclencher, alors que `projects/services/automation_registration.py` en
documente un. Vingt-cinq publieurs sur vingt-six étaient corrects : ce
n'était pas une dérive générale, c'était un trou unique au point le plus
central.

**Pourquoi aucun test ne rougissait.** Les six tests d'`automation`
publient `workflow.transitioned` **avec un `tenant_id` explicite**, sans
jamais passer par le vrai publieur. Le chemin réel n'était exercé nulle
part. Même motif que le test BI-4 corrigé au lot L9 : vert parce qu'il
court-circuite ce qu'il prétend vérifier.

**Pourquoi une garde statique plutôt qu'un test d'intégration.** Un test
d'intégration ne couvre que les publieurs qu'il connaît. Le vingt-septième
publieur sera écrit par quelqu'un qui n'aura pas lu ce fichier — et la
seule chose qui l'arrêtera est un test qui lit le code source, pas un test
qui exerce les vingt-six premiers.
"""

from __future__ import annotations

import ast
from pathlib import Path

APPS_DIR = Path(__file__).resolve().parent.parent.parent / "apps"

#: Le bus lui-même déclare `tenant_id` en paramètre optionnel : c'est sa
#: signature, pas un appel.
FICHIER_DU_BUS = APPS_DIR / "core" / "events.py"

#: Sites d'appel légitimement sans société, avec le motif écrit. Vide
#: aujourd'hui, et c'est le point : la liste existe pour qu'une exception
#: future soit une DÉCISION, pas un oubli. Y ajouter une entrée oblige à
#: écrire pourquoi cet événement n'a volontairement aucun destinataire
#: automatisable.
SANS_SOCIETE_ASSUME: dict[str, str] = {}


def _fichiers_de_production() -> list[Path]:
    fichiers = []
    for chemin in APPS_DIR.rglob("*.py"):
        texte = str(chemin)
        if "/tests/" in texte or chemin.name.startswith("test_"):
            continue
        if "/migrations/" in texte:
            continue
        if chemin == FICHIER_DU_BUS:
            continue
        fichiers.append(chemin)
    return fichiers


def _appels_de_publication() -> list[tuple[str, int, list[str]]]:
    """Chaque `publish_event(...)` de production : (chemin relatif, ligne,
    noms des arguments nommés)."""
    appels = []
    for chemin in _fichiers_de_production():
        source = chemin.read_text(encoding="utf-8")
        if "publish_event(" not in source:
            continue
        arbre = ast.parse(source, filename=str(chemin))
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.Call):
                continue
            fonction = noeud.func
            nom = (
                fonction.id
                if isinstance(fonction, ast.Name)
                else fonction.attr
                if isinstance(fonction, ast.Attribute)
                else None
            )
            if nom != "publish_event":
                continue
            relatif = str(chemin.relative_to(APPS_DIR.parent))
            appels.append((relatif, noeud.lineno, [k.arg for k in noeud.keywords if k.arg]))
    return appels


def test_every_production_publisher_names_its_company() -> None:
    """La garde elle-même. Un `publish_event` sans `tenant_id` publie un
    événement que `dispatch_event_to_flows` jette : il est écrit dans
    `core_event_log` et n'atteint aucun flux."""
    manquants = [
        f"{fichier}:{ligne}"
        for fichier, ligne, arguments in _appels_de_publication()
        if "tenant_id" not in arguments and fichier not in SANS_SOCIETE_ASSUME
    ]
    assert not manquants, (
        "Ces publications d'événement ne nomment aucune société — "
        "`automation/services/dispatch.py` les ignorera, donc aucun AutoFlow "
        f"ne pourra jamais s'y brancher : {manquants}. Renseigner `tenant_id=`, "
        "ou inscrire le motif dans `SANS_SOCIETE_ASSUME` si l'absence est "
        "délibérée."
    )


def test_the_guard_actually_sees_the_publishers() -> None:
    """Une garde qui ne trouve rien passe toujours. Le dépôt compte
    vingt-six sites de publication en production ; en trouver zéro, ou
    seulement deux, signifierait que la détection est cassée — pas que le
    code est propre.

    Le seuil est délibérément bas et non exact : il détecte une détection
    en panne, sans rougir chaque fois qu'un module publie un événement de
    plus."""
    appels = _appels_de_publication()
    assert len(appels) >= 20, (
        f"Seulement {len(appels)} appels à `publish_event` détectés en "
        "production. La détection AST ne voit plus les publieurs — la garde "
        "ci-dessus serait verte pour rien."
    )


def test_a_documented_exception_names_a_file_that_exists() -> None:
    """Une exception qui désigne un fichier disparu est une exception qui ne
    protège plus rien, et qui masque le publieur qui a pris sa place."""
    for fichier, motif in SANS_SOCIETE_ASSUME.items():
        assert (APPS_DIR.parent / fichier).exists(), (
            f"`SANS_SOCIETE_ASSUME` désigne {fichier}, qui n'existe plus."
        )
        assert len(motif) > 40, (
            f"Le motif de {fichier} tient en moins de quarante caractères : "
            "ce n'est pas une décision écrite, c'est une case cochée."
        )
