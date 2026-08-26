"""MRP-FPY1 (enrichissement WideHalo) : taux de premier passage (FPY) et
analyse de Pareto des principales causes de defauts."""

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
