"""S3 — le registre des adaptateurs : ou l'executeur trouve QUI appeler.

**Un registre en memoire, pas une table.** `FlwConnector` est la
DECLARATION d'un connecteur, editable par le client ; l'adaptateur est le
CODE qui sait lui parler, livre par l'editeur. Les stocker au meme endroit
melangerait une donnee de production et un artefact de livraison — et
permettrait a une ligne de base de designer un adaptateur qui n'existe pas
dans la version deployee. Meme patron que
`core.services.anomaly_registry` et `core.services.scheduled_commands` :
chaque module declare ce qu'il apporte depuis son `apps.py::ready()`.

**Le registre est VIDE au sprint S3, et c'est normal.** Le bloc A livre un
adaptateur factice au sprint S6 ; les vrais connecteurs arrivent au bloc C
et au-dela. Ce qui compte est que la vidange se comporte correctement
maintenant : un echange dont le connecteur n'a pas d'adaptateur RESTE EN
FILE, sans appel et sans echec. L'inverse — le marquer en echec — ferait
d'un deploiement partiel une perte de donnees, et d'une montee de version
un incident.

C'est aussi pourquoi la commande periodique existe des maintenant plutot
qu'au sprint S6. La lecon du lot WhatsApp est ecrite dans
`apps/whatsapp/management/commands/run_whatsapp_queue.py` : un mecanisme de
reprise sans declencheur automatique n'est pas une file, c'est un bouton.
Livrer la file sans son declencheur reproduirait exactement ce defaut, six
sprints avant qu'on ne s'en apercoive.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.flows.services.queue import Sender

_ADAPTERS: dict[str, Sender] = {}


def register_adapter(connector_code: str, sender: Sender) -> None:
    """Declare l'adaptateur d'un code de connecteur. Idempotent : un meme
    code re-enregistre remplace l'entree, ce qui rend le rechargement en
    developpement sans effet de bord."""
    _ADAPTERS[connector_code] = sender


def get_adapter(connector_code: str) -> Sender | None:
    return _ADAPTERS.get(connector_code)


def has_adapter(connector_code: str) -> bool:
    return connector_code in _ADAPTERS


def list_adapters() -> list[str]:
    return sorted(_ADAPTERS)


__all__ = ["get_adapter", "has_adapter", "list_adapters", "register_adapter"]
