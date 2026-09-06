"""Contrat public du hub de flux — seule surface que les autres apps metier
ont le droit d'importer (cf. `tests/architecture/test_module_boundaries.py`).

**Le sens de la dependance est inverse de l'intuition, et c'est voulu.**
`flows` ne declare aucune dependance metier : c'est `accounting`, `sales` ou
`logistics` qui declareront `flows` le jour ou ils emettront un echange. Un
module metier appelle donc les fonctions ci-dessous ; le hub, lui, ne
rappelle jamais un module metier — il rend un resultat, et l'appelant en
fait ce qu'il veut.

Consequence pratique pour l'appelant : il designe sa piece par un couple
`(document_type, document_id)` de son choix, jamais par un objet. Le hub ne
resoudra jamais ce couple ; il le transporte et le rend, pour que l'appelant
retrouve ses propres pieces.

A ce sprint (S1), la surface se limite a la LECTURE : le registre existe,
les ecritures viennent avec la machine a etats (S2) et la file (S3). Poser
des fonctions d'ecriture ici avant que la machine a etats n'existe
reviendrait a laisser un appelant creer un echange dans un etat que rien ne
fait avancer — un enregistrement mort dans le registre, exactement le motif
que cette equipe corrige depuis le debut du projet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.flows.models import FlwExchange, FlwLink

if TYPE_CHECKING:
    from uuid import UUID

    from apps.core.models.tenant import Tenant


def list_exchanges_for_document(
    tenant: Tenant, *, document_type: str, document_id: UUID, limit: int = 20
) -> list[dict[str, Any]]:
    """Historique des echanges rattaches a UNE piece metier.

    Repond a « qu'est devenue cette facture chez le tiers ? » depuis la
    fiche de la piece, sans que le module appelant ait a connaitre
    `FlwExchange`. Renvoie des dicts primitifs, jamais l'objet ORM (regle de
    couplage n°1), tries du plus recent au plus ancien.

    Liste vide, jamais une exception, si la piece n'a jamais donne lieu a un
    echange : c'est le cas NORMAL pour l'immense majorite des pieces, pas
    une anomalie a signaler."""
    exchanges = FlwExchange.objects.filter(
        tenant=tenant, document_type=document_type, document_id=document_id
    ).order_by("-created_at")[:limit]
    return [
        {
            "id": exchange.id,
            "direction": exchange.direction,
            "operation": exchange.operation,
            "state": exchange.state,
            "attempt": exchange.attempt,
            "result_code": exchange.result_code,
            "correlation_key": exchange.correlation_key,
            "sent_at": exchange.sent_at,
            "settled_at": exchange.settled_at,
        }
        for exchange in exchanges
    ]


def count_exchanges_awaiting_verdict(tenant: Tenant) -> int:
    """Nombre d'echanges partis dont le tiers n'a pas encore tranche.

    Chiffre destine a la console de flux et au tableau de bord : c'est le
    seul etat ou l'entreprise a fait sa part et attend quelqu'un d'autre.
    Le distinguer de « en echec » evite de presenter comme une panne ce qui
    est un delai normal chez l'administration ou la banque."""
    return FlwExchange.objects.filter(
        tenant=tenant, state=FlwExchange.STATE_AWAITING_VERDICT
    ).count()


def has_active_link(tenant: Tenant, *, connector_code: str) -> bool:
    """`True` si ce tenant a une liaison ACTIVE sur ce connecteur.

    Permet a un module metier de n'afficher une action d'envoi que lorsque
    le canal existe reellement, plutot que de proposer un bouton qui
    echouera. C'est la liaison qui est interrogee, jamais le connecteur :
    sur une instance multi-societes, deux tenants branches sur le meme
    adaptateur ont deux enrolements independants."""
    return FlwLink.objects.filter(
        tenant=tenant, connector__code=connector_code, state=FlwLink.STATE_ACTIVE
    ).exists()


__all__ = [
    "count_exchanges_awaiting_verdict",
    "has_active_link",
    "list_exchanges_for_document",
]
