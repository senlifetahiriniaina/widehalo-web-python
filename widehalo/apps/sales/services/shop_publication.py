"""T7 (bloc G, COM-3) — ce qu'on publie comme disponible, et ce que ce mot
veut dire.

**Le critère** : « la publication de disponibilité reflète le stock
**disponible à la vente** au sens de la Phase 3, réservations déduites, et
non le stock physique. »

**Toute la difficulté tient dans un mot, et la Phase 3 l'a déjà tranché.**
`stocks.services.reservations.available_to_sell` — RG-STK-8 — vaut
`qty − qty_reserved`, agrégé sur les emplacements INTERNES uniquement.
Publier le stock physique reviendrait à vendre ce qui est déjà promis à
quelqu'un d'autre : la boutique accepterait la commande, et c'est à la
préparation qu'on découvrirait qu'il n'y a rien à expédier.

**Ce module ne recalcule rien.** Il lit la primitive existante par la
surface publique de `stocks` et l'envoie. Refaire la soustraction ici
produirait une seconde définition du disponible, et le jour où la Phase 3
affinerait la sienne — un emplacement de plus, un statut de quarantaine —
la boutique publierait l'ancienne sans que rien ne proteste.

**La publication passe par le hub (OP2), jamais par un appel réseau.**
Règle de couplage n°1, vérifiée par une garde CI depuis S6. `sales` dit ce
qu'il veut publier ; le hub sait à qui et comment.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import TYPE_CHECKING, Any

from django.utils import timezone

from apps.catalog.services.public import get_variant_reference
from apps.flows.services.public import publish_dataset
from apps.stocks.services.public import get_available_stock_qty

if TYPE_CHECKING:
    from uuid import UUID

    from apps.core.models.tenant import Tenant

#: Le connecteur vers lequel la disponibilité part. Le même que celui d'où
#: viennent les commandes : une boutique qui nous envoie des commandes est
#: celle à qui on publie ce qu'elle peut vendre.
CONNECTOR_CODE = "boutique"


def publish_availability(
    tenant: Tenant,
    *,
    variant_ids: list[UUID],
    now: dt.datetime | None = None,
) -> dict[str, Any] | None:
    """Publie la disponibilité À LA VENTE des articles demandés.

    Rend `None` si aucune liaison active ne sert la boutique — état normal
    d'une installation qui ne vend pas en ligne, pas une panne.

    **L'occurrence est l'HORODATAGE de la passe**, à la minute. Une
    publication de disponibilité se refait sans cesse ; sans occurrence
    distincte, la deuxième heurterait la contrainte d'idempotence du hub et
    la planification mourrait au deuxième passage, en silence. À la minute
    et non à la seconde : deux passes lancées dans la même minute publient
    la même chose, et les distinguer n'apprendrait rien à personne."""
    if not variant_ids:
        return None

    horodatage = now or timezone.now()
    lignes = [
        {
            "sku": get_variant_reference(variant_id),
            # **`get_available_stock_qty` et non `qty`** : c'est
            # `qty − qty_reserved` sur les emplacements internes (RG-STK-8),
            # c'est-à-dire ce qu'on peut réellement promettre. Publier le
            # physique vendrait ce qui est déjà promis.
            "available_qty": str(get_available_stock_qty(variant_id)),
        }
        for variant_id in variant_ids
    ]
    corps = json.dumps(
        {"as_of": horodatage.isoformat(), "availability": lignes},
        sort_keys=True,
    )
    return publish_dataset(
        tenant,
        connector_code=CONNECTOR_CODE,
        body=corps,
        occurrence=horodatage.strftime("%Y-%m-%dT%H:%M"),
    )


__all__ = ["CONNECTOR_CODE", "publish_availability"]
