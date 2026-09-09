"""T5 (bloc B, API-3 et API-5) — le point d'entrée entrant du hub.

**Ce qui n'existait pas, et que le dépôt croyait avoir.** Deux endroits du
code référencent ce point d'entrée comme s'il était écrit :
`adapters/reference.py` dit que « le point d'entrée de webhook du bloc B
(API-6, S7-S9) **appellera** » `receive_event`, et que
« l'authentification de l'appelant et la protection contre le rejeu sont
au point d'entrée de webhook du bloc B, **pas ici** ». Elles n'étaient
donc nulle part : `receive_event` n'avait aucun appelant.

**Les deux critères, et ce qu'ils imposent séparément.**

API-3 : « un appel non signé, mal signé ou horodaté hors fenêtre est
rejeté sans traitement, et journalisé **sans révéler le motif à
l'appelant** ». D'où un 403 nu dans tous les cas de refus, et le motif
dans le journal.

API-5 : « le point d'entrée accuse réception en **moins de 500 ms** sous
charge nominale, le traitement étant **différé en file** ». D'où la forme
de cette vue : elle écrit l'échange entrant, publie sur le bus, et rend la
main. Aucun traitement métier n'a lieu ici — c'est ce que `whatsapp` fait
à l'envers, en appelant `handle_inbound_message` dans le thread web.

**Le hub publie, il ne rappelle jamais un module métier.** C'est la règle
que la docstring de `services/public.py` pose depuis S1. Un abonné
d'`accounting` reçoit `flows.inbound_received` et décide seul quoi en
faire ; `flows` n'a pas à savoir qu'un module de comptabilité existe.

**Le tenant vient de la LIAISON, jamais d'un en-tête.** Un opérateur
mobile money n'envoie pas de `X-Tenant-Id`, et le lui faire envoyer
reviendrait à laisser l'appelant choisir la société dans laquelle il
écrit. `FlwLink.all_objects` est donc lu hors contexte de tenant — même
nécessité que `carrier_webhook_endpoint`, et mêmes précautions.
"""

from __future__ import annotations

import logging
from typing import Any

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from ninja import Router

from apps.core.events import publish_event
from apps.core.tenant_context import activate_tenant
from apps.flows.models import FlwLink
from apps.flows.services.webhook_auth import (
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    verify_inbound_call,
)

logger = logging.getLogger(__name__)

router = Router(tags=["flows-webhooks"])

#: L'événement publié à l'arrivée. Le nom dit ce qui EST arrivé, pas ce
#: qu'il faut en faire : c'est l'abonné qui décide, et deux abonnés peuvent
#: en tirer deux conclusions différentes sans que le hub ait à trancher.
EVENT_INBOUND_RECEIVED = "flows.inbound_received"


@router.post("/flows/webhooks/{link_id}", auth=None)
def inbound_webhook(request: Any, link_id: str) -> HttpResponse:
    """Accuse réception d'un appel entrant, ou le refuse sans rien dire.

    **Le 403 est nu, dans tous les cas de refus.** Distinguer « signature
    invalide » de « horodatage hors fenêtre » apprendrait à qui essaie où
    il en est. Le motif part au journal, où l'exploitant le lit.

    **Le 200 ne dit pas que le traitement a réussi** — il dit que l'appel
    est reçu et enregistré. C'est exactement ce qu'API-5 demande, et c'est
    aussi ce qui protège l'opérateur : un tiers qui attend un 2xx re-livre
    tant qu'il ne l'obtient pas, et faire dépendre l'accusé d'un traitement
    métier transformerait une lenteur comptable en tempête de re-livraisons.
    """
    liaison = get_object_or_404(FlwLink.all_objects, id=link_id)

    # **Le contexte de société est posé ICI, avant toute lecture.** Un
    # opérateur n'envoie pas de `X-Tenant-Id` — le lui faire envoyer
    # reviendrait à laisser l'appelant choisir la société dans laquelle il
    # écrit — donc aucun middleware n'a posé la session Postgres, et tout
    # `TenantManager` (refus par défaut) rend vide.
    #
    # Le défaut que cela ferme était silencieux et coûteux : la lecture du
    # secret rendait vide, la vérification concluait « aucun secret
    # configuré », et un appel PARFAITEMENT SIGNÉ était refusé. Un
    # raccordement réel n'aurait jamais fonctionné, et le journal aurait
    # accusé une configuration absente qui, elle, était bien là.
    #
    # Poser le contexte plutôt que lire en `all_objects` : le manager en
    # refus par défaut reste actif pour tout ce qui suit, y compris
    # l'écriture de l'échange, au lieu d'ouvrir une porte par commodité.
    with activate_tenant(liaison.tenant_id):
        return _handle_authenticated_call(request, liaison, link_id)


def _handle_authenticated_call(request: Any, liaison: FlwLink, link_id: str) -> HttpResponse:
    """La suite, SOUS le contexte de la société de la liaison."""
    verdict = verify_inbound_call(
        liaison,
        payload=request.body,
        signature=request.headers.get(HEADER_SIGNATURE, ""),
        timestamp=request.headers.get(HEADER_TIMESTAMP, ""),
    )
    if not verdict.accepted:
        # Journalisé AVEC le motif, rendu SANS. Le `link_id` suffit à
        # l'exploitant pour retrouver la liaison ; le corps n'est pas
        # journalisé, il peut porter des données du payeur.
        logger.warning("webhook entrant refusé (liaison=%s) : %s", link_id, verdict.reason)
        return HttpResponse(status=403)

    if liaison.state != FlwLink.STATE_ACTIVE:
        # Une liaison suspendue refuse aussi, et pour une raison qui n'a
        # rien à voir avec l'authentification : on suspend précisément
        # parce que les échanges posent problème. Le motif diffère, la
        # réponse est la même.
        logger.warning("webhook entrant sur liaison non active (liaison=%s)", link_id)
        return HttpResponse(status=403)

    from apps.flows.adapters.reference import receive_event

    echange = receive_event(liaison.tenant, liaison, body=request.body.decode("utf-8", "replace"))

    publish_event(
        EVENT_INBOUND_RECEIVED,
        {
            "exchange_id": str(echange.id),
            "link_id": str(liaison.id),
            "connector_code": liaison.connector.code,
            "operation": echange.operation,
            "correlation_key": echange.correlation_key,
        },
        tenant_id=str(liaison.tenant_id),
    )
    return HttpResponse(status=200)


__all__ = ["EVENT_INBOUND_RECEIVED", "inbound_webhook", "router"]
