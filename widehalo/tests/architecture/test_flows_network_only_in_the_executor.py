"""Garde-fou bloquant — FLX-1, première moitié : aucun appel réseau hors de
l'exécuteur du hub.

Le critère, mot pour mot : « un test d'intégration continue échoue si un
adaptateur émet un appel réseau sortant EN DEHORS DE L'EXÉCUTEUR DU HUB, ou
si un échange est écrit sans empreinte de contenu. » La seconde moitié est
tenue par le refus posé sur le passage à `emis`
(`services/exchange.py`), vérifiée par
`test_s2_exchange_state_machine.py::test_an_exchange_without_a_fingerprint_can_never_be_emitted`.
Celle-ci tient la première.

**Ce qui rend l'interdit nécessaire, et pas seulement propre.** L'exécuteur
n'est pas un passage obligé décoratif : c'est lui, et lui seul, qui porte
les trois bornes du cahier (§11) — délai maximal par appel, budget de
passe, plafond de rafale par connecteur — et le disjoncteur par liaison
(FLX-3). Un service qui appellerait un tiers directement contournerait les
quatre d'un coup. Ce dépôt en a déjà l'exemple : `models.py` annonçait
cette garde en commentaire depuis le sprint S1, et personne ne l'avait
écrite.

**Deux interdits, parce qu'un seul se contourne.** Le premier porte sur les
BIBLIOTHÈQUES réseau, autorisées dans les seuls modules d'adaptateur — un
adaptateur EST ce que l'exécuteur appelle, c'est donc là et nulle part
ailleurs que le réseau a le droit d'exister. Le second porte sur le
REGISTRE : lire `get_adapter` ailleurs que dans l'exécuteur permettrait
d'invoquer un adaptateur à la main, avec toutes ses bornes contournées, sans
qu'aucune bibliothèque réseau n'apparaisse dans le module fautif.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.architecture._ast_utils import APPS_DIR

FLOWS_DIR = APPS_DIR / "flows"

#: Modules dont le seul usage est de parler au réseau, ou de lancer quelque
#: chose qui le fera. `subprocess` en fait partie : un `curl` lancé en
#: sous-processus est un appel réseau qu'aucune liste de bibliothèques HTTP
#: n'attraperait.
RESEAU = frozenset(
    {
        "aiohttp",
        "ftplib",
        "http",
        "httpcore",
        "httplib2",
        "httpx",
        "paramiko",
        "requests",
        "smtplib",
        "socket",
        "ssl",
        "subprocess",
        "telnetlib",
        "urllib",
        "urllib3",
        "websocket",
        "websockets",
    }
)

#: Le seul répertoire où le réseau a le droit d'apparaître : les
#: adaptateurs, c'est-à-dire précisément ce que l'exécuteur appelle.
REPERTOIRE_DES_ADAPTATEURS = FLOWS_DIR / "adapters"

#: Le module qui EST l'exécuteur. Seul lui a le droit de résoudre un
#: adaptateur dans le registre.
EXECUTEUR = FLOWS_DIR / "services" / "queue.py"

#: Ce que « résoudre un adaptateur » veut dire, sous forme de noms.
RESOLUTION_D_ADAPTATEUR = frozenset({"get_adapter", "_ADAPTERS"})

#: Exceptions, avec leur motif écrit. Vide, et c'est l'état recherché : une
#: liste d'exceptions qui se remplit est le premier signe qu'un interdit
#: n'était pas tenable. Chemin relatif à `apps/flows/`.
EXCEPTIONS_RESEAU: dict[str, str] = {}


def _fichiers_scrutes() -> list[Path]:
    """Tout `apps/flows/`, tests et migrations exclus.

    Les tests sont exclus délibérément : un test a le droit de simuler un
    appel réseau, c'est même souvent la seule façon de vérifier qu'on le
    refuse. Les migrations le sont parce qu'elles ne s'exécutent jamais
    dans une passe de vidange."""
    return sorted(
        chemin
        for chemin in FLOWS_DIR.rglob("*.py")
        if "/tests/" not in str(chemin)
        and not chemin.name.startswith("test_")
        and "/migrations/" not in str(chemin)
    )


def _racine(module: str) -> str:
    return module.split(".")[0]


def modules_reseau_dans(source: str, nom: str = "<source>") -> list[str]:
    """Les modules réseau importés par cette source. Prend la source EN
    ARGUMENT, et c'est ce qui rend l'auto-test écrivable sans toucher au
    disque — leçon de `test_no_raw_sql_in_reporting.py`, qui écrit puis
    supprime un vrai fichier sous `apps/`."""
    arbre = ast.parse(source, filename=nom)
    trouves = []
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            trouves.extend(alias.name for alias in noeud.names if _racine(alias.name) in RESEAU)
        elif isinstance(noeud, ast.ImportFrom) and noeud.module and _racine(noeud.module) in RESEAU:
            trouves.append(noeud.module)
    return sorted(set(trouves))


def resolutions_d_adaptateur_dans(source: str, nom: str = "<source>") -> list[str]:
    """Les endroits où cette source va chercher un adaptateur dans le
    registre — par import, par attribut ou par appel."""
    arbre = ast.parse(source, filename=nom)
    trouves = []
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.ImportFrom) and noeud.module:
            trouves.extend(
                alias.name for alias in noeud.names if alias.name in RESOLUTION_D_ADAPTATEUR
            )
        elif isinstance(noeud, ast.Attribute) and noeud.attr in RESOLUTION_D_ADAPTATEUR:
            trouves.append(noeud.attr)
        elif isinstance(noeud, ast.Name) and noeud.id in RESOLUTION_D_ADAPTATEUR:
            trouves.append(noeud.id)
    return sorted(set(trouves))


# --- Interdit n°1 : le réseau ---------------------------------------------------


def test_no_network_library_outside_the_adapters() -> None:
    fautifs = {}
    for chemin in _fichiers_scrutes():
        relatif = str(chemin.relative_to(FLOWS_DIR))
        if chemin.is_relative_to(REPERTOIRE_DES_ADAPTATEURS) or relatif in EXCEPTIONS_RESEAU:
            continue
        modules = modules_reseau_dans(chemin.read_text(encoding="utf-8"), relatif)
        if modules:
            fautifs[relatif] = modules
    assert fautifs == {}, (
        "Appel réseau possible hors d'un adaptateur : l'exécuteur porte le "
        "délai maximal par appel, le budget de passe, le plafond de rafale et "
        "le disjoncteur — les contourner, c'est les perdre tous les quatre. "
        f"{fautifs}"
    )


def test_the_guard_actually_reads_the_module() -> None:
    """Une garde qui ne scrute rien reste verte pour toujours. Le seuil est
    volontairement bas et ne bougera pas : il dit « le répertoire est
    trouvé », pas « le module a la bonne taille »."""
    fichiers = _fichiers_scrutes()
    assert len(fichiers) >= 15, f"Seulement {len(fichiers)} fichier(s) scruté(s)."
    assert any(chemin.name == "queue.py" for chemin in fichiers)
    assert any(chemin.is_relative_to(REPERTOIRE_DES_ADAPTATEURS) for chemin in fichiers)


def test_the_detector_catches_a_network_call() -> None:
    """L'auto-test, sur les trois formes qu'un import peut prendre."""
    assert modules_reseau_dans("import requests") == ["requests"]
    assert modules_reseau_dans("from urllib.request import urlopen") == ["urllib.request"]
    assert modules_reseau_dans("import httpx as client") == ["httpx"]
    assert modules_reseau_dans("import subprocess") == ["subprocess"]
    # Le témoin : sans lui, un détecteur qui répondrait TOUJOURS laisserait
    # les quatre assertions ci-dessus vertes.
    assert modules_reseau_dans("import json\nfrom django.db import models") == []


# --- Interdit n°2 : le registre -------------------------------------------------


def test_only_the_executor_resolves_an_adapter() -> None:
    """Un module qui résoudrait un adaptateur lui-même l'appellerait hors
    des bornes, sans qu'aucune bibliothèque réseau n'apparaisse chez lui —
    c'est exactement le contournement que le premier interdit ne voit
    pas."""
    fautifs = {}
    for chemin in _fichiers_scrutes():
        if chemin == EXECUTEUR or chemin.name == "adapter_registry.py":
            continue
        trouves = resolutions_d_adaptateur_dans(chemin.read_text(encoding="utf-8"))
        if trouves:
            fautifs[str(chemin.relative_to(FLOWS_DIR))] = trouves
    assert fautifs == {}, (
        "Résolution d'adaptateur hors de l'exécuteur : l'appel se ferait sans "
        f"disjoncteur, sans budget et sans plafond de rafale. {fautifs}"
    )


def test_the_executor_really_resolves_one() -> None:
    """Le témoin de l'interdit n°2. Sans lui, un détecteur muet rendrait le
    test précédent vert, et l'exécuteur pourrait perdre sa résolution
    d'adaptateur sans que rien ne proteste."""
    trouves = resolutions_d_adaptateur_dans(EXECUTEUR.read_text(encoding="utf-8"))
    assert "get_adapter" in trouves


def test_the_detector_catches_a_registry_read() -> None:
    assert resolutions_d_adaptateur_dans(
        "from apps.flows.services.adapter_registry import get_adapter"
    ) == ["get_adapter"]
    assert resolutions_d_adaptateur_dans("adapter_registry._ADAPTERS['x'](e, 1)") == ["_ADAPTERS"]
    assert resolutions_d_adaptateur_dans("from apps.flows.models import FlwExchange") == []


# --- Les motifs -----------------------------------------------------------------


@pytest.mark.parametrize("chemin,motif", sorted(EXCEPTIONS_RESEAU.items()))
def test_every_exception_is_motivated(chemin: str, motif: str) -> None:
    """Une exception sans motif écrit n'est pas une décision, c'est une case
    cochée. Quarante caractères, même seuil que les autres gardes du
    dépôt."""
    assert len(motif) >= 40, f"{chemin} : motif trop court pour être une décision."


def test_the_exception_list_has_no_obsolete_entry() -> None:
    for chemin in EXCEPTIONS_RESEAU:
        assert (FLOWS_DIR / chemin).exists(), f"{chemin} n'existe plus."
