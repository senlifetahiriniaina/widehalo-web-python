"""T7 (bloc G) — ce qui écoute le hub et fait entrer les commandes.

**Rien à réinventer : T5 a construit le chemin.** Le point d'entrée entrant
générique existe depuis le bloc D — une boutique signe son appel, le hub
authentifie, enregistre l'échange et publie `flows.inbound_received`. Ce
module est l'autre bout : il écoute, reconnaît son connecteur, et ingère.

**Pourquoi un abonné et pas un appel depuis le hub.** La règle posée depuis
S1 : « le hub ne rappelle jamais un module métier — il rend un résultat, et
l'appelant en fait ce qu'il veut ». `flows` n'a pas à savoir qu'un module
de vente existe. C'est le miroir exact de ce que `accounting` fait pour les
encaissements.

**L'abonné ne lève jamais pour un cas normal.** Le bus réessaie trois fois
avant de marquer un échec. Un échange qui ne concerne pas une boutique, une
charge utile illisible, une commande déjà connue : les trois sont l'état
habituel d'une installation, et lever produirait trois tentatives inutiles
puis une trace d'échec pour un fonctionnement nominal.

**Ce qu'il ne fait pas, et c'est COM-1.** Il ne confirme aucune commande.
`confirm_order` déclenche la qualification d'approvisionnement, donc des
mouvements de stock — exactement ce que le critère interdit à une commande
ingérée. La garde `tests/architecture/test_ingested_orders_stay_at_the
_initial_state.py` le vérifie plutôt que de compter sur cette docstring.
"""

from __future__ import annotations

import logging
from typing import Any

from apps.core.events import subscribe

logger = logging.getLogger(__name__)


def register_shop_subscribers() -> None:
    """Appelée depuis `apps.py::ready()`, même patron que les autres
    registres du dépôt."""

    @subscribe("flows.inbound_received")
    def _on_inbound_received(event: dict[str, Any]) -> None:
        from apps.core.models.tenant import Tenant
        from apps.core.tenant_context import activate_tenant
        from apps.flows.services.public import read_inbound_payload
        from apps.sales.services.shop_ingest import CONNECTOR_CODE, ingest_shop_orders

        payload = event.get("payload") or {}
        if payload.get("connector_code") != CONNECTOR_CODE:
            return

        tenant_id = event.get("tenant_id")
        exchange_id = payload.get("exchange_id")
        if not tenant_id or not exchange_id:
            return

        tenant = Tenant.objects.filter(id=tenant_id).first()
        if tenant is None:
            # La société a pu être supprimée entre la publication et la
            # distribution. Rare, mais pas anormal — et lever ferait
            # réessayer trois fois quelque chose qui n'existe plus.
            return

        with activate_tenant(tenant.id):
            corps = read_inbound_payload(tenant, exchange_id=exchange_id)
            if corps is None:
                # Charge utile purgée (FLX-5) : l'échange reste, sa trace
                # aussi ; il n'y a simplement plus rien à lire.
                logger.info("échange entrant %s sans charge utile lisible", exchange_id)
                return

            rapport = ingest_shop_orders(
                tenant,
                corps,
                # Le code de boutique vient de la LIAISON, jamais de la
                # charge utile : le laisser à l'appelant reviendrait à
                # permettre à une boutique de se déclarer être une autre,
                # et donc de lire — ou d'écraser — les commandes d'un
                # concurrent servi par la même instance.
                shop_code=str(payload.get("link_id") or ""),
            )

        if rapport.rejected:
            logger.warning(
                "ingestion boutique (échange %s) : %s commande(s) refusée(s)",
                exchange_id,
                len(rapport.rejected),
            )


__all__ = ["register_shop_subscribers"]
