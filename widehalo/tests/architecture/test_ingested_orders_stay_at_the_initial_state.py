"""Garde-fou bloquant (T7, COM-1 contre l'interdit §4.4) : une commande
ingérée ne franchit jamais son statut initial.

**Le critère** : « une commande ingérée crée un document **au statut
initial** et ne produit ni facture, ni mouvement de stock, ni écriture,
conformément à l'interdit de la section 4.4 ».

**Ce que la mesure a rendu net, et sans quoi cette garde serait vague.**
`sales.services.orders.confirm_order` appelle
`procurement.qualify_and_process_order` : confirmer une commande qualifie
chaque ligne et déclenche réellement l'approvisionnement — réservation de
stock, demande d'achat, ordre de fabrication. Une ingestion qui confirmerait
produirait donc exactement les trois choses que COM-1 interdit, sans qu'un
seul appel n'ait l'air fautif.

**Ce que ce fichier mesure, et ce qu'aucun test de comportement ne peut
tenir.** Le test de comportement vérifie que les commandes ingérées
AUJOURD'HUI restent en `draft`. Il ne dit rien du module qui, demain,
appellerait `confirm_order` depuis l'abonné « pour rendre service » — et
aucun test existant ne rougirait, puisqu'il ne connaîtrait pas ce module.
La propriété structurelle est donc : **le chemin d'ingestion ne peut pas
atteindre la confirmation**.
"""

from __future__ import annotations

import ast
from pathlib import Path

#: Les fichiers du chemin d'ingestion : ce qui reçoit d'un tiers et écrit
#: une commande. Ils sont nommés un par un, jamais devinés par un motif de
#: nom — une liste explicite se relit, un motif attrape un jour un fichier
#: qu'on n'avait pas en tête et en manque un autre.
_INGESTION_PATHS = [
    "apps/sales/services/shop_ingest.py",
    "apps/sales/services/shop_registration.py",
]

#: Les noms qui font passer une commande de `draft` à autre chose, ou qui
#: déclenchent l'approvisionnement. Les importer depuis le chemin
#: d'ingestion, c'est pouvoir produire ce que COM-1 interdit.
_FORBIDDEN_NAMES = {
    "confirm_order",
    "send_order",
    "qualify_and_process_order",
    "invoice_order",
    "mark_delivered",
    "attempt_transition",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _names_used(path: Path) -> set[str]:
    """Tout nom importé OU appelé dans ce fichier.

    Les deux, parce que l'un sans l'autre laisse une porte : un import
    seul ne prouve pas l'appel, mais `from ... import confirm_order` suffit
    à rendre l'appel possible, et un appel par attribut
    (`orders.confirm_order(...)`) n'apparaît dans aucun import de nom."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    trouves: set[str] = set()
    for noeud in ast.walk(tree):
        if isinstance(noeud, ast.ImportFrom):
            trouves.update(alias.name for alias in noeud.names)
        elif isinstance(noeud, ast.Call):
            cible = noeud.func
            if isinstance(cible, ast.Name):
                trouves.add(cible.id)
            elif isinstance(cible, ast.Attribute):
                trouves.add(cible.attr)
    return trouves


def test_the_ingestion_path_can_never_confirm_an_order() -> None:
    """Aucun fichier du chemin d'ingestion ne nomme ce qui fait sortir une
    commande de son statut initial."""
    racine = _repo_root()
    violations: list[str] = []
    for relatif in _INGESTION_PATHS:
        fichier = racine / relatif
        if not fichier.exists():
            continue
        interdits = _names_used(fichier) & _FORBIDDEN_NAMES
        if interdits:
            violations.append(f"{relatif} : {sorted(interdits)}")

    assert not violations, (
        "COM-1 : le chemin d'ingestion peut faire sortir une commande de son "
        "statut initial :\n" + "\n".join(violations) + "\n\n"
        "Une commande ingérée est PROPOSÉE, jamais disposée : `confirm_order` "
        "déclenche la qualification d'approvisionnement, donc des mouvements de "
        "stock. C'est un humain qui confirme, après avoir vu ce qui est arrivé."
    )


def test_the_guard_watches_a_path_that_exists() -> None:
    """Une garde qui surveille un fichier disparu ne surveille rien.

    Elle passerait pour toujours, et le jour où le module reviendrait sous
    un autre nom personne ne rejouerait la décision. Au moins un des
    chemins déclarés doit exister."""
    racine = _repo_root()
    existants = [chemin for chemin in _INGESTION_PATHS if (racine / chemin).exists()]
    assert existants, (
        "Aucun des chemins d'ingestion déclarés n'existe : cette garde ne "
        "surveille plus rien. Mettre `_INGESTION_PATHS` à jour, ou la retirer "
        "en connaissance de cause."
    )


def test_the_forbidden_names_still_exist_where_they_are_expected() -> None:
    """Les noms interdits doivent être ceux qui existent réellement.

    Un nom mal orthographié dans la liste est une interdiction qui ne
    portera jamais — la garde resterait verte quoi qu'on écrive. On vérifie
    donc que les deux plus importants sont bien définis là où on les
    croit."""
    racine = _repo_root()
    orders = (racine / "apps/sales/services/orders.py").read_text(encoding="utf-8")
    procurement = (racine / "apps/sales/services/procurement.py").read_text(encoding="utf-8")

    assert "def confirm_order(" in orders, (
        "`confirm_order` n'est plus défini dans `services/orders.py` : "
        "l'interdiction porte sur un nom qui n'existe plus."
    )
    assert "def qualify_and_process_order(" in procurement, (
        "`qualify_and_process_order` n'est plus défini dans "
        "`services/procurement.py` : l'interdiction ne porte plus sur rien."
    )
