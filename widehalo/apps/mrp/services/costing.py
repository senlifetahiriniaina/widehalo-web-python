"""Cout de revient (RG-MRP-6) en 3 composantes, calcule en planifie a
l'ouverture (a partir des quantites/durees planifiees) et en reel a la
cloture (a partir des consommations et durees reelles), avec ecart
explicite par composante. RG-MRP-11 : ecart de consommation avec motif
obligatoire au-dela d'un seuil parametrable.

Le cout unitaire de valorisation des composants (FIFO/CMP) depend du futur
module `stocks` (non construit) — fourni explicitement en parametre par
l'appelant en attendant, plutot que fige en dur."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.mrp.models import MrpOrder, MrpOrderComponent

DEFAULT_VARIANCE_THRESHOLD_PCT = Decimal(5)


def _material_cost(
    order: MrpOrder, *, qty_field: str, component_unit_costs: dict[UUID, Decimal]
) -> Decimal:
    total = Decimal(0)
    for component in order.components.select_related("bom_line").all():
        unit_cost = component_unit_costs.get(component.bom_line.component_template_id, Decimal(0))
        total += getattr(component, qty_field) * unit_cost
    return total


def _labor_cost(order: MrpOrder, *, duration_field: str) -> Decimal:
    total = Decimal(0)
    for work_order in order.work_orders.select_related("workcenter").all():
        duration_min = getattr(work_order, duration_field)
        hours = Decimal(duration_min) / Decimal(60)
        total += hours * work_order.workcenter.cost_per_hour_mga
    return total


def compute_planned_cost(
    order: MrpOrder, *, component_unit_costs: dict[UUID, Decimal], overhead_rate_pct: Decimal
) -> dict[str, Decimal]:
    material = _material_cost(
        order, qty_field="qty_planned", component_unit_costs=component_unit_costs
    )
    labor = _labor_cost(order, duration_field="duration_planned_min")
    overhead = labor * overhead_rate_pct / Decimal(100)
    total = material + labor + overhead

    order.cost_material_planned_mga = material
    order.cost_labor_planned_mga = labor
    order.cost_overhead_planned_mga = overhead
    order.cost_total_planned_mga = total
    order.save(
        update_fields=[
            "cost_material_planned_mga",
            "cost_labor_planned_mga",
            "cost_overhead_planned_mga",
            "cost_total_planned_mga",
        ]
    )
    return {"material": material, "labor": labor, "overhead": overhead, "total": total}


def compute_real_cost(
    order: MrpOrder, *, component_unit_costs: dict[UUID, Decimal], overhead_rate_pct: Decimal
) -> dict[str, Any]:
    """A n'appeler qu'a la cloture (RG-MRP-6) — seul un CRA valide entre
    dans ce calcul (filtre applique par l'appelant, cf. services/cra.py)."""
    material = _material_cost(
        order, qty_field="qty_consumed", component_unit_costs=component_unit_costs
    )
    labor = _labor_cost(order, duration_field="duration_real_min")
    overhead = labor * overhead_rate_pct / Decimal(100)
    total = material + labor + overhead

    order.cost_material_mga = material
    order.cost_labor_mga = labor
    order.cost_overhead_mga = overhead
    order.cost_total_mga = total
    order.save(
        update_fields=["cost_material_mga", "cost_labor_mga", "cost_overhead_mga", "cost_total_mga"]
    )

    return {
        "material": material,
        "labor": labor,
        "overhead": overhead,
        "total": total,
        "variance_material": material - order.cost_material_planned_mga,
        "variance_labor": labor - order.cost_labor_planned_mga,
        "variance_overhead": overhead - order.cost_overhead_planned_mga,
        "variance_total": total - order.cost_total_planned_mga,
    }


def consume_component(
    component: MrpOrderComponent,
    *,
    qty_consumed: Decimal,
    reason: str = "",
    threshold_pct: Decimal = DEFAULT_VARIANCE_THRESHOLD_PCT,
) -> MrpOrderComponent:
    """RG-MRP-11 : l'ecart entre consommation planifiee et reelle est
    constate ligne a ligne ; motif obligatoire au-dela du seuil."""
    if component.qty_planned:
        variance_pct = (
            abs(qty_consumed - component.qty_planned) / component.qty_planned * Decimal(100)
        )
    else:
        variance_pct = Decimal(100) if qty_consumed else Decimal(0)

    if variance_pct > threshold_pct and not reason:
        raise ValidationError(
            _("Un motif est obligatoire : l'ecart de consommation depasse le seuil autorise.")
        )

    component.qty_consumed = qty_consumed
    component.variance_reason = reason
    component.state = "consumed"
    component.save(update_fields=["qty_consumed", "variance_reason", "state"])
    return component
