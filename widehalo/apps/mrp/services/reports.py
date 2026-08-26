"""Rapports MRP (§5.3.6) : MRP-OF, MRP-COST, MRP-CRA, MRP-CRI, MRP-PROD,
MRP-EFF, MRP-SCRAP, MRP-CHARGE."""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
from decimal import Decimal
from typing import Any

from django.db.models import Count, Sum

from apps.mrp.models import MrpCra, MrpCri, MrpOrder, MrpScrap, MrpWorkOrder, MrpWorkshop


def rows_to_bytes(rows: list[dict[str, Any]], fields: list[str], *, format: str = "json") -> bytes:
    if format == "json":
        return json.dumps(rows, indent=2, ensure_ascii=False, default=str).encode("utf-8")

    if format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        return buffer.getvalue().encode("utf-8")

    if format == "xlsx":
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(fields)
        for row in rows:
            sheet.append([row.get(field) for field in fields])
        buffer_bytes = io.BytesIO()
        workbook.save(buffer_bytes)
        return buffer_bytes.getvalue()

    raise ValueError(f"Format d'export non supporte : {format}")


def order_pdf(order: MrpOrder) -> bytes:
    """MRP-OF — ordre de fabrication avec nomenclature et gamme, PDF
    bilingue minimal (meme patron que ACC-FAC)."""
    from weasyprint import HTML

    components_html = "".join(
        f"<tr><td>{c.bom_line.component_template_id}</td><td>{c.qty_planned}</td>"
        f"<td>{c.qty_consumed}</td></tr>"
        for c in order.components.select_related("bom_line").all()
    )
    steps_html = ""
    if order.routing is not None:
        steps_html = "".join(
            f"<tr><td>{s.sequence}</td><td>{s.operation.name}</td><td>{s.duration_min}</td></tr>"
            for s in order.routing.steps.all()
        )

    html = f"""
    <html><head><meta charset="utf-8"></head><body>
      <h1>Ordre de fabrication / Manufacturing order {order.reference}</h1>
      <p>Atelier / Workshop : {order.workshop.name}</p>
      <p>Quantite / Quantity : {order.qty}</p>
      <h2>Composants / Components</h2>
      <table border="1" cellspacing="0" cellpadding="4">
        <thead><tr><th>Composant</th><th>Planifie</th><th>Consomme</th></tr></thead>
        <tbody>{components_html}</tbody>
      </table>
      <h2>Gamme / Routing</h2>
      <table border="1" cellspacing="0" cellpadding="4">
        <thead><tr><th>#</th><th>Operation</th><th>Duree (min)</th></tr></thead>
        <tbody>{steps_html}</tbody>
      </table>
    </body></html>
    """
    result: bytes = HTML(string=html).write_pdf()
    return result


def cost_report(order: MrpOrder) -> dict[str, Any]:
    """MRP-COST — cout planifie / reel / ecart, par composante."""
    return {
        "reference": order.reference,
        "material_planned": order.cost_material_planned_mga,
        "material_real": order.cost_material_mga,
        "material_variance": order.cost_material_mga - order.cost_material_planned_mga,
        "labor_planned": order.cost_labor_planned_mga,
        "labor_real": order.cost_labor_mga,
        "labor_variance": order.cost_labor_mga - order.cost_labor_planned_mga,
        "overhead_planned": order.cost_overhead_planned_mga,
        "overhead_real": order.cost_overhead_mga,
        "overhead_variance": order.cost_overhead_mga - order.cost_overhead_planned_mga,
        "total_planned": order.cost_total_planned_mga,
        "total_real": order.cost_total_mga,
        "total_variance": order.cost_total_mga - order.cost_total_planned_mga,
    }


def cra_summary(
    *,
    date_from: dt.date,
    date_to: dt.date,
    workshop: MrpWorkshop | None = None,
) -> list[dict[str, Any]]:
    """MRP-CRA — recapitulatif par employe et par atelier."""
    queryset = MrpCra.objects.filter(date__gte=date_from, date__lte=date_to)
    if workshop is not None:
        queryset = queryset.filter(workshop=workshop)

    rows = (
        queryset.values("employee__email", "workshop__code", "state")
        .annotate(total_hours=Sum("hours"), total_qty_done=Sum("qty_done"))
        .order_by("workshop__code", "employee__email")
    )
    return [
        {
            "employee": row["employee__email"],
            "workshop": row["workshop__code"],
            "state": row["state"],
            "total_hours": row["total_hours"] or Decimal(0),
            "total_qty_done": row["total_qty_done"] or Decimal(0),
        }
        for row in rows
    ]


def cri_summary(*, date_from: dt.date, date_to: dt.date) -> list[dict[str, Any]]:
    """MRP-CRI — interventions et temps d'arret sur la periode."""
    queryset = MrpCri.objects.filter(date__gte=date_from, date__lte=date_to)
    rows = (
        queryset.values("workcenter__code", "type")
        .annotate(total_downtime_min=Sum("downtime_min"), count=Count("id"))
        .order_by("workcenter__code", "type")
    )
    return [
        {
            "workcenter": row["workcenter__code"],
            "type": row["type"],
            "total_downtime_min": row["total_downtime_min"] or 0,
            "count": row["count"],
        }
        for row in rows
    ]


def production_report(
    workshop: MrpWorkshop, *, date_from: dt.date, date_to: dt.date
) -> list[dict[str, Any]]:
    """MRP-PROD — production par atelier et par periode."""
    orders = MrpOrder.objects.filter(
        workshop=workshop, date_end__date__gte=date_from, date_end__date__lte=date_to
    )
    return [
        {
            "reference": o.reference,
            "qty_produced": o.qty_produced,
            "qty_scrapped": o.qty_scrapped,
            "date_end": o.date_end,
        }
        for o in orders
    ]


def efficiency_report(workcenter_code: str | None = None) -> list[dict[str, Any]]:
    """MRP-EFF — rendement par poste (qty_done / (qty_done+qty_rejected))."""
    queryset = MrpWorkOrder.objects.filter(state=MrpWorkOrder.STATE_DONE)
    if workcenter_code is not None:
        queryset = queryset.filter(workcenter__code=workcenter_code)

    rows = queryset.values("workcenter__code").annotate(
        total_done=Sum("qty_done"), total_rejected=Sum("qty_rejected")
    )
    results = []
    for row in rows:
        done = row["total_done"] or Decimal(0)
        rejected = row["total_rejected"] or Decimal(0)
        total = done + rejected
        efficiency_pct = (done / total * Decimal(100)) if total else Decimal(0)
        results.append(
            {
                "workcenter": row["workcenter__code"],
                "qty_done": done,
                "qty_rejected": rejected,
                "efficiency_pct": efficiency_pct,
            }
        )
    return results


def scrap_report(*, date_from: dt.date, date_to: dt.date) -> list[dict[str, Any]]:
    """MRP-SCRAP — analyse des rebuts par motif."""
    queryset = MrpScrap.objects.filter(date__gte=date_from, date__lte=date_to)
    rows = (
        queryset.values("reason")
        .annotate(total_qty=Sum("qty"), total_cost=Sum("cost_mga"))
        .order_by("-total_qty")
    )
    return [
        {
            "reason": row["reason"],
            "total_qty": row["total_qty"] or Decimal(0),
            "total_cost_mga": row["total_cost"] or Decimal(0),
        }
        for row in rows
    ]


def workload_report(workshop: MrpWorkshop) -> list[dict[str, Any]]:
    """MRP-CHARGE — charge planifiee par poste (ordres non clotures)."""
    queryset = MrpWorkOrder.objects.filter(order__workshop=workshop).exclude(
        order__state__in=[MrpOrder.STATE_CLOSED, MrpOrder.STATE_CANCELLED]
    )
    rows = (
        queryset.values("workcenter__code")
        .annotate(total_planned_min=Sum("duration_planned_min"))
        .order_by("workcenter__code")
    )
    return [
        {"workcenter": row["workcenter__code"], "total_planned_min": row["total_planned_min"] or 0}
        for row in rows
    ]
