"""RG-SAL-3 (qualification d'origine par ligne, §5.5.3, S3 du
sous-sequencement `sales`, cf. plan) : a la confirmation d'une commande de
vente, chaque ligne est traitee selon l'origine deja qualifiee
(`SalesOrderLine.source`, ecrite des S1) :

- **"a produire" (`SOURCE_PRODUCTION`)** : branche **reelle** depuis S3 —
  resout le `product_template_id` de la ligne via
  `catalog.services.public.get_variant_template_id`, puis appelle
  `mrp.services.public.create_manufacturing_order`. Un `MrpOrder` reel est
  cree quand une nomenclature active existe (et qu'un atelier est
  disponible) ; sinon la ligne est marquee "necessite une planification
  manuelle de production", jamais une exception.
- **"sur stock" (`SOURCE_STOCK`)** : **reelle** depuis le chantier de
  durcissement retroactif qui leve ce stub (`apps.stocks` existe desormais
  — cf. plan, §5.8) — appelle `stocks.services.public.
  check_and_reserve_stock` avec `variant_id`/`qty` de la ligne. Une
  reservation reelle est fabriquee (`SalesOrderLine.stock_reservation_id`
  renseigne) quand un quant unique suffit a couvrir la quantite demandee ;
  sinon la ligne reste `pending_stock` — un reliquat legitime de "stock
  reellement insuffisant" (ou fractionne sur plusieurs quants, cf.
  simplification assumee documentee sur `check_and_reserve_stock`), pas
  une limitation de code.
- **"a acheter" (`SOURCE_ACHAT`)** : **reelle** depuis le meme chantier
  (`apps.purchase` existe desormais) — appelle `purchase.services.public.
  create_requisition_line_from_source`, qui cree une VRAIE demande d'achat
  (`PurRequisition`/`PurRequisitionLine`) en brouillon uniquement (jamais
  soumise/approuvee automatiquement). `SalesOrderLine.purchase_order_
  line_id` stocke alors l'UUID de la `PurRequisitionLine` cree (PAS d'une
  `PurOrderLine` — le cycle demande -> RFQ -> commande reste une decision
  humaine/metier, hors perimetre de cette qualification automatique).
  Reste `pending_purchase` si aucun utilisateur `purchase` valide n'a pu
  etre resolu pour `requester_user_id` (cas normal : un `core.User` cote
  vente n'a pas forcement de role d'acheteur cote achats).

La branche "a produire" reste testee sans deviation via le test
d'acceptance §5.5.8 n°1 du CDC ; les deux autres branches sont desormais
elles aussi couvertes par un document reel — cf.
`apps/sales/tests/test_procurement.py`, qui verifie a la fois le chemin
"reservation/demande reelle" ET le repli legitime `pending_stock`/
`pending_purchase` quand la condition metier (stock insuffisant, requester
non resolu) n'est pas reunie."""

from __future__ import annotations

from typing import Any

from apps.catalog.services.public import get_variant_template_id
from apps.core.models.user import User
from apps.mrp.services.public import create_manufacturing_order
from apps.purchase.services.public import create_requisition_line_from_source
from apps.sales.models import SalesOrder, SalesOrderLine
from apps.stocks.services.public import check_and_reserve_stock


def qualify_and_process_order(order: SalesOrder, user: User) -> dict[str, Any]:
    """Qualifie et traite chaque ligne de `order` selon son `source` deja
    ecrit. Ne leve jamais d'exception pour un cas non qualifiable (ligne
    hors catalogue sans `variant_id`, absence de nomenclature/atelier,
    stock insuffisant, requester d'achat non resolu) — ces cas sont
    simplement reportes dans le dict retourne, jamais silencieusement
    ignores.

    `user` sert desormais (chantier de durcissement retroactif) a resoudre
    `requester_user_id` pour la branche "a acheter" — reste par ailleurs
    inutilise pour les deux autres branches (aucune trace d'auteur sur
    `MrpOrder`/la reservation de stock en l'etat)."""
    summary: dict[str, list[str]] = {
        "produced": [],
        "reserved_from_stock": [],
        "pending_stock": [],
        "reserved_from_purchase": [],
        "pending_purchase": [],
        "needs_manual_production": [],
    }

    for line in order.lines.all():
        if line.source == SalesOrderLine.SOURCE_PRODUCTION:
            _qualify_production_line(line, order, summary)
        elif line.source == SalesOrderLine.SOURCE_STOCK:
            _qualify_stock_line(line, order, summary)
        elif line.source == SalesOrderLine.SOURCE_ACHAT:
            _qualify_purchase_line(line, order, user, summary)

    return summary


def _qualify_stock_line(
    line: SalesOrderLine, order: SalesOrder, summary: dict[str, list[str]]
) -> None:
    """RG-SAL-3 "sur stock", desormais reelle (cf. docstring module). Ligne
    hors catalogue sans `variant_id` (`is_custom`) : aucune reservation
    automatique possible (meme garde defensive que
    `_qualify_production_line`), reste `pending_stock`."""
    if line.variant_id is None:
        summary["pending_stock"].append(str(line.id))
        return

    reservation_id = check_and_reserve_stock(
        order.tenant, variant_id=line.variant_id, qty=line.qty, date=order.date, source_object=line
    )
    if reservation_id is None:
        summary["pending_stock"].append(str(line.id))
        return

    line.stock_reservation_id = reservation_id
    line.save(update_fields=["stock_reservation_id"])
    summary["reserved_from_stock"].append(str(line.id))


def _qualify_purchase_line(
    line: SalesOrderLine, order: SalesOrder, user: User, summary: dict[str, list[str]]
) -> None:
    """RG-SAL-3 "a acheter", desormais reelle (cf. docstring module). Ligne
    hors catalogue sans `variant_id` : aucune demande d'achat automatique
    possible (une demande d'achat exige un `variant_id` reel, cf.
    `PurRequisitionLine.variant_id`), reste `pending_purchase` — meme garde
    defensive que les deux autres branches."""
    if line.variant_id is None:
        summary["pending_purchase"].append(str(line.id))
        return

    requisition_line_id = create_requisition_line_from_source(
        order.tenant,
        requester_user_id=user.id,
        variant_id=line.variant_id,
        qty=line.qty,
        date_needed=order.commitment_date or order.date,
        description=line.description,
    )
    if requisition_line_id is None:
        summary["pending_purchase"].append(str(line.id))
        return

    line.purchase_order_line_id = requisition_line_id
    line.save(update_fields=["purchase_order_line_id"])
    summary["reserved_from_purchase"].append(str(line.id))


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


def get_procurement_plan(order: SalesOrder) -> dict[str, Any]:
    """`GET .../orders/{id}/procurement-plan` (§5.5.7) — differe de S3 a S7
    (cf. plan). Lecture SEULE de l'etat de qualification RG-SAL-3 deja
    ecrit par `qualify_and_process_order` a la confirmation : ne
    recree/ne relance jamais rien (jamais un second `MrpOrder`/une seconde
    reservation/demande d'achat pour la meme ligne) — c'est un rapport,
    pas une re-qualification. Une commande pas encore confirmee n'a jamais
    ete qualifiee : chaque ligne y apparait avec le statut
    `"not_yet_qualified"`.

    Les branches "sur stock"/"a acheter" distinguent desormais (chantier
    de durcissement retroactif) leur issue REELLE — `"reserved_from_
    stock"`/`"reserved_from_purchase"` quand un document reel existe deja
    sur la ligne (`stock_reservation_id`/`purchase_order_line_id`
    renseigne), `"pending_stock"`/`"pending_purchase"` sinon (repli
    legitime, pas une erreur)."""
    lines: list[dict[str, Any]] = []
    for line in order.lines.all():
        if line.mrp_order_id is not None:
            status = "produced"
        elif order.state == SalesOrder.STATE_DRAFT or order.state == SalesOrder.STATE_SENT:
            status = "not_yet_qualified"
        elif line.source == SalesOrderLine.SOURCE_STOCK:
            status = (
                "reserved_from_stock" if line.stock_reservation_id is not None else "pending_stock"
            )
        elif line.source == SalesOrderLine.SOURCE_ACHAT:
            status = (
                "reserved_from_purchase"
                if line.purchase_order_line_id is not None
                else "pending_purchase"
            )
        elif line.source == SalesOrderLine.SOURCE_PRODUCTION:
            status = "needs_manual_production"
        else:  # pragma: no cover - garde defensive, choix SOURCE_CHOICES exhaustifs
            status = "unknown"
        lines.append(
            {
                "line_id": str(line.id),
                "source": line.source,
                "status": status,
                "mrp_order_id": str(line.mrp_order_id) if line.mrp_order_id else None,
                "stock_reservation_id": (
                    str(line.stock_reservation_id) if line.stock_reservation_id else None
                ),
                "purchase_order_line_id": (
                    str(line.purchase_order_line_id) if line.purchase_order_line_id else None
                ),
                "qty_to_produce": line.qty_to_produce,
            }
        )
    return {"order_id": str(order.id), "lines": lines}
