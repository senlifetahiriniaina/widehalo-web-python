"""Garde-fou bloquant — les deux moitiés de la file dédiée ne divergent pas.

La « troisième file de worker, dédiée aux échanges » (cahier Phase 4 §7.6)
n'existe que si DEUX réglages concordent :

1. `FLOWS_QUEUE_CLUSTER_NAME` côté application, qui décide à quel cluster
   `sync_scheduled_commands` attribue la commande de vidange ;
2. `Q_CLUSTER_NAME` sur un service worker, qui décide quelle file Redis ce
   worker consomme et quelles planifications son ordonnanceur accepte.

**Le mode de panne est le pire qui soit : silencieux et total.** Le
planificateur de Django-Q ne prend une planification que si son `cluster`
correspond au sien (`django_q/scheduler.py`, filtre
`Q(cluster__isnull=True) | Q(cluster=CLUSTER_NAME)`, la première branche
étant réservée au cluster par défaut). Si les deux noms divergent — une
faute de frappe, un service renommé, une moitié copiée sans l'autre — la
commande de vidange n'est exécutée par personne. Aucune exception, aucune
ligne de journal, aucune tâche en échec : les échanges s'accumulent en file
et le premier signal est un client qui demande où est sa facture.

Ce test ne vérifie pas un déploiement réel — il ne le peut pas. Il vérifie
que le fichier de composition livré est cohérent AVEC LUI-MÊME, ce qui est
le seul endroit où les deux valeurs sont visibles côte à côte.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
COMPOSE = REPO_ROOT / "docker-compose.prod.yml"


def _env_values(nom: str) -> list[str]:
    texte = COMPOSE.read_text(encoding="utf-8")
    return re.findall(rf"^\s*{nom}:\s*(\S+)\s*$", texte, flags=re.MULTILINE)


def test_the_compose_file_exists() -> None:
    """Sans lui, les deux tests suivants seraient verts par construction —
    `findall` sur un fichier absent lèverait, mais un chemin qui glisse
    d'un répertoire les rendrait muets."""
    assert COMPOSE.exists(), f"Fichier de composition introuvable : {COMPOSE}"


def test_the_application_setting_and_the_worker_name_agree() -> None:
    applicatif = _env_values("FLOWS_QUEUE_CLUSTER_NAME")
    worker = _env_values("Q_CLUSTER_NAME")

    if not applicatif:
        # L'isolation n'est pas activée dans ce fichier : rien à vérifier,
        # et pas d'erreur — le cluster partagé est un déploiement valide.
        assert not worker, (
            f"Un worker déclare Q_CLUSTER_NAME={worker} mais aucun service ne règle "
            "FLOWS_QUEUE_CLUSTER_NAME : ce worker tourne à vide, la vidange reste sur "
            "le cluster partagé."
        )
        return

    assert worker, (
        f"FLOWS_QUEUE_CLUSTER_NAME={applicatif} est réglé mais aucun service worker ne "
        "porte Q_CLUSTER_NAME : la commande de vidange serait attribuée à un cluster "
        "qui ne tourne pas, et ne s'exécuterait JAMAIS — sans aucune erreur."
    )
    assert set(applicatif) <= set(worker), (
        f"Les deux moitiés de la file dédiée divergent : l'application attribue la "
        f"vidange à {sorted(set(applicatif))}, les workers consomment {sorted(set(worker))}. "
        "La file de sortie ne serait vidée par personne, en silence."
    )


def test_a_dedicated_worker_actually_runs_a_cluster() -> None:
    """Un service qui porte `Q_CLUSTER_NAME` sans lancer `qcluster` serait
    un nom sans consommateur — même panne silencieuse, un cran plus tôt."""
    texte = COMPOSE.read_text(encoding="utf-8")
    if "Q_CLUSTER_NAME" not in texte:
        return
    bloc = texte[texte.index("worker-flux:") :]
    fin = re.search(r"\n  [a-z][a-z0-9_-]*:\n", bloc)
    bloc = bloc[: fin.start()] if fin else bloc
    assert "qcluster" in bloc, (
        "Le service `worker-flux` ne lance pas `manage.py qcluster` : il porte un nom "
        "de cluster que rien ne consomme."
    )
    assert "Q_CLUSTER_NAME" in bloc, (
        "Le service `worker-flux` ne porte pas Q_CLUSTER_NAME : il consommerait la file "
        "partagée, sans isoler quoi que ce soit."
    )
