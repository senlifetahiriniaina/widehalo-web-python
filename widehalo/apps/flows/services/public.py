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

A S1, la surface se limitait a la LECTURE : « poser des fonctions
d'ecriture ici avant que la machine a etats n'existe reviendrait a laisser
un appelant creer un echange dans un etat que rien ne fait avancer ». La
machine a etats (S2) et la file (S3) existent depuis, et T3 ouvre donc la
premiere ecriture : `request_reference_lookup`, l'operation OP8. La
condition posee en S1 est levee, pas contournee — un echange cree par
cette fonction part en file et la vidange le fait avancer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.flows.models import FlwExchange, FlwLink
from apps.flows.operations import OP_QUERY_REFERENCE

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


def request_reference_lookup(
    tenant: Tenant,
    *,
    connector_code: str,
    document_type: str,
    document_id: UUID,
    body: str = "",
) -> dict[str, Any] | None:
    """OP8 — demande au hub d'interroger un referentiel, et rend la main.

    **Le cahier decrit OP8 comme « synchrone », et il ne peut pas l'etre
    ici.** §4.1 : « Interroger un referentiel | Sortant, lecture |
    Synchrone | Verifier un identifiant fiscal [...] | Mise en cache avec
    duree de validite, degradation en valeur saisie si le tiers ne repond
    pas ». Deux regles deja tenues l'interdisent telle quelle : aucun
    module metier n'emet d'appel reseau (regle de couplage n°1, garde CI
    depuis S6), et l'echec d'un tiers ne bloque jamais une transition
    metier (FLX-2).

    La lecture retenue : la demande part EN FILE, et le resultat ANNOTE la
    piece quand il arrive. La valeur saisie reste autoritative tant qu'elle
    n'est pas contredite — c'est exactement ce que « degradation en valeur
    saisie » decrit, et c'est la seule lecture compatible avec les deux
    regles. Creer un tiers ne dependra jamais de la latence d'un
    referentiel.

    Rend `None` quand aucune liaison active ne sert ce connecteur : ne pas
    avoir branche de referentiel est un etat parfaitement normal, pas une
    erreur a signaler. L'appelant continue avec la valeur saisie."""
    from apps.flows.services.exchange import prepare_exchange
    from apps.flows.services.queue import queue_exchange

    link = (
        FlwLink.objects.filter(
            tenant=tenant, connector__code=connector_code, state=FlwLink.STATE_ACTIVE
        )
        .select_related("connector")
        .first()
    )
    if link is None:
        return None

    exchange = queue_exchange(
        prepare_exchange(
            tenant,
            link,
            operation=OP_QUERY_REFERENCE,
            document_type=document_type,
            document_id=document_id,
            body=body,
        )
    )
    return {
        "id": exchange.id,
        "state": exchange.state,
        "operation": exchange.operation,
        "correlation_key": exchange.correlation_key,
    }


__all__ = [
    "count_exchanges_awaiting_verdict",
    "has_active_link",
    "list_exchanges_for_document",
    "request_reference_lookup",
]
