"""RG-SAL-3 (qualification d'origine par ligne, §5.5.3, S3 du
sous-sequencement `sales`, cf. plan) : a la confirmation d'une commande de
vente, chaque ligne est traitee selon l'origine deja qualifiee
(`SalesOrderLine.source`, ecrite des S1) :

- **"a produire" (`SOURCE_PRODUCTION`)** : branche **reelle** — resout le
  `product_template_id` de la ligne via
  `catalog.services.public.get_variant_template_id`, puis appelle
  `mrp.services.public.create_manufacturing_order`. Un `MrpOrder` reel est
  cree quand une nomenclature active existe (et qu'un atelier est
  disponible) ; sinon la ligne est marquee "necessite une planification
  manuelle de production", jamais une exception.
- **"sur stock" (`SOURCE_STOCK`)** : **stubee** — `apps.stocks` n'existe pas
  encore dans ce lot (l'ordre acte du Lot 2 place SALES avant STOCKS). La
  disponibilite repond toujours "indisponible", exactement comme le stub de
  faisabilite CRM (RG-CRM-7) : jamais un faux positif. Aucune reservation
  n'est fabriquee.
- **"a acheter" (`SOURCE_ACHAT`)** : **stubee** — `apps.purchase` n'existe
  pas encore non plus. La ligne est marquee en attente, `purchase_order_
  line_id` reste nul.

Ces deux stubs sont documentes comme deviation assumee par rapport au test
d'acceptance §5.5.8 n°1 du CDC (qui envisage un document reel pour les
trois branches) — cf. plan, section "Module `sales`", decisions de
sequencement RG-SAL-3, et `apps/sales/tests/test_procurement.py` qui
verifie explicitement cette deviation."""

from __future__ import annotations

from typing import Any

from apps.catalog.services.public import get_variant_template_id
from apps.core.models.user import User
from apps.mrp.services.public import create_manufacturing_order
from apps.sales.models import SalesOrder, SalesOrderLine


def qualify_and_process_order(order: SalesOrder, user: User) -> dict[str, Any]:
    """Qualifie et traite chaque ligne de `order` selon son `source` deja
    ecrit. Ne leve jamais d'exception pour un cas non qualifiable (ligne
    hors catalogue sans `variant_id`, absence de nomenclature/atelier) —
    ces cas sont simplement reportes dans le dict retourne, jamais
    silencieusement ignores.

    `user` n'est pas encore utilise (aucune trace d'auteur sur
    `MrpOrder`/la qualification en l'etat) mais est accepte des maintenant
    pour que la signature n'ait pas a changer quand un tel besoin
    apparaitra (ex. tracabilite S7)."""
    del user  # reserve, cf. docstring — pas encore de trace d'auteur necessaire.

    summary: dict[str, list[str]] = {
        "produced": [],
        "pending_stock": [],
        "pending_purchase": [],
        "needs_manual_production": [],
    }

    for line in order.lines.all():
        if line.source == SalesOrderLine.SOURCE_PRODUCTION:
            _qualify_production_line(line, order, summary)
        elif line.source == SalesOrderLine.SOURCE_STOCK:
            # Stub RG-SAL-3 "sur stock" : `apps.stocks` n'existe pas encore
            # — disponibilite toujours "indisponible", aucune reservation
            # fabriquee (cf. docstring module).
            summary["pending_stock"].append(str(line.id))
        elif line.source == SalesOrderLine.SOURCE_ACHAT:
            # Stub RG-SAL-3 "a acheter" : `apps.purchase` n'existe pas
            # encore — la ligne reste en attente, `purchase_order_line_id`
            # ne change jamais ici.
            summary["pending_purchase"].append(str(line.id))

    return summary


def _qualify_production_line(
    line: SalesOrderLine, order: SalesOrder, summary: dict[str, list[str]]
) -> None:
    if line.variant_id is None:
        # Ligne hors catalogue (`is_custom`) : aucune nomenclature ne peut
        # lui etre rattachee automatiquement — jamais une exception, une
        # planification manuelle reste possible cote production.
        summary["needs_manual_production"].append(str(line.id))
        return

    product_template_id = get_variant_template_id(line.variant_id)
    if product_template_id is None:
        summary["needs_manual_production"].append(str(line.id))
        return

    mrp_order_id = create_manufacturing_order(
        tenant=order.tenant,
        product_template_id=product_template_id,
        variant_id=line.variant_id,
        qty=line.qty,
    )
    if mrp_order_id is None:
        summary["needs_manual_production"].append(str(line.id))
        return

    line.mrp_order_id = mrp_order_id
    line.qty_to_produce = line.qty
    line.save(update_fields=["mrp_order_id", "qty_to_produce"])
    summary["produced"].append(str(line.id))
