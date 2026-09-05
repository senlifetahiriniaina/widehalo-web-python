"""MRP-FPY1 (enrichissement WideHalo) : taux de premier passage (FPY) et
analyse de Pareto des principales causes de defauts.

**PRD-6 (L12-4)** : `first_pass_yield_from_moves` ci-dessous recalcule le
taux depuis les MOUVEMENTS DE STOCK, ce que le critere exige et qui etait
impossible jusqu'a ce lot — `mrp` ne produisait aucun `StkMove.TYPE_REBUT`.
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Count

from apps.mrp.models import MrpCri, MrpOrder, MrpWorkshop

PARETO_TOP_N = 5


def first_pass_yield(order: MrpOrder) -> Decimal:
    """FPY = quantite bonne du premier coup / quantite totale traitee, sur
    l'ensemble des ordres de travail de l'ordre de fabrication."""
    total_done = Decimal(0)
    total_rejected = Decimal(0)
    for work_order in order.work_orders.all():
        total_done += work_order.qty_done
        total_rejected += work_order.qty_rejected

    total = total_done + total_rejected
    if not total:
        return Decimal(0)
    return (total_done / total) * Decimal(100)


def scrapped_qty_by_workstation(order: MrpOrder) -> dict[int, Decimal]:
    """Quantite rejetee PAR POSTE, lue sur les mouvements de stock.

    Passe par `stocks.services.public.list_scrap_quantities_by_source`
    (regle de couplage n1 : `mrp` ne lit jamais `StkMove`). La cle est le
    `sequence` de l'ordre de travail, resolu depuis le `source_document`
    que `services.orders.scrap_source_document` a pose a la declaration.

    Un poste absent du resultat n'a produit aucun mouvement de rebut — donc
    zero, et non une donnee manquante."""
    # Import local : `services.orders` importe deja `stocks.services.public`
    # en local pour la meme raison (cycle reel via `apps.mrp.apps.ready()`).
    from apps.mrp.services.orders import scrap_source_document
    from apps.stocks.services.public import list_scrap_quantities_by_source

    work_orders = list(order.work_orders.all())
    by_document = {scrap_source_document(order, wo): wo for wo in work_orders}
    quantities = list_scrap_quantities_by_source(order.tenant, source_documents=list(by_document))
    return {
        work_order.sequence: quantities.get(document, Decimal(0))
        for document, work_order in by_document.items()
    }


def first_pass_yield_from_moves(order: MrpOrder) -> Decimal:
    """FPY recalcule depuis les mouvements de stock (PRD-6).

    Doit valoir EXACTEMENT `first_pass_yield(order)` — c'est le critere :
    « recalculable a l'identique depuis les mouvements ».

    **Ce que cette fonction prend reellement aux mouvements, et ce qu'elle
    ne peut pas leur prendre.** La quantite REJETEE de chaque poste vient
    des `StkMove.TYPE_REBUT` que `done_work_order` produit desormais. La
    quantite BONNE, elle, n'a aucune contrepartie par poste : le seul
    mouvement d'entree de production (`production_in`) porte sur l'ordre
    entier, et il n'existe aucune trace physique du passage conforme a un
    poste intermediaire. Elle est donc lue sur `MrpWorkOrder.qty_done`.

    Le dire plutot que de laisser croire le contraire : un critere a moitie
    prouve, annonce comme entierement prouve, serait pire que le 🟡 qu'il
    remplace. Ce que le recalcul etablit est neanmoins reel et non trivial —
    que les mouvements portent exactement la quantite rejetee declaree,
    POSTE PAR POSTE, sans en perdre ni en compter deux fois.

    **Pourquoi par poste.** Le FPY somme sur tous les ordres de travail :
    sur une gamme a trois postes, la meme piece est comptee trois fois. Une
    somme naive des mouvements de rebut d'un ordre — sans distinction de
    poste — donne donc un taux faux ; c'est exactement ce que la convention
    de `source_document` evite, et ce que les tests exercent.

    Renvoie `Decimal(0)` sur un ordre sans aucun passage, comme
    `first_pass_yield`."""
    scrapped = scrapped_qty_by_workstation(order)
    total_done = Decimal(0)
    total_rejected = Decimal(0)
    for work_order in order.work_orders.all():
        total_done += work_order.qty_done
        total_rejected += scrapped.get(work_order.sequence, Decimal(0))

    total = total_done + total_rejected
    if not total:
        return Decimal(0)
    return (total_done / total) * Decimal(100)


def first_pass_yield_by_workshop(workshop: MrpWorkshop) -> Decimal:
    total_done = Decimal(0)
    total_rejected = Decimal(0)
    for order in workshop.orders.all():
        for work_order in order.work_orders.all():
            total_done += work_order.qty_done
            total_rejected += work_order.qty_rejected

    total = total_done + total_rejected
    if not total:
        return Decimal(0)
    return (total_done / total) * Decimal(100)


def pareto_defect_causes(workshop: MrpWorkshop | None = None) -> list[dict[str, object]]:
    """Regroupe les CRI de type `incident_qualite` par cause, retourne les
    `PARETO_TOP_N` causes les plus frequentes (loi de Pareto : 80/20)."""
    queryset = MrpCri.objects.filter(type=MrpCri.TYPE_QUALITY_INCIDENT).exclude(cause="")
    if workshop is not None:
        queryset = queryset.filter(workcenter__workshop=workshop)

    rows = queryset.values("cause").annotate(count=Count("id")).order_by("-count")[:PARETO_TOP_N]
    return [{"cause": row["cause"], "count": row["count"]} for row in rows]
