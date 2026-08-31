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

from apps.mrp.models import MrpBom, MrpOrder, MrpOrderComponent
from apps.mrp.services.bom import explode
from apps.mrp.services.cra import real_labor_cost

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


def simulate_bom_cost(
    bom: MrpBom,
    qty: Decimal,
    *,
    component_unit_costs: dict[UUID, Decimal],
    overhead_rate_pct: Decimal,
) -> dict[str, Decimal]:
    """Simulation PURE du cout de revient d'une `MrpBom` pour une quantite
    hypothetique — gap ajoute pour `feasibility.services.simulation`
    (chantier FEA1-3, cf. plan) : une etude de faisabilite doit pouvoir
    chiffrer un produit AVANT qu'un `MrpOrder` reel n'existe (pas de client/
    prospect reel, juste une nomenclature deja saisie et une quantite
    d'hypothese).

    **Extraction, pas reimplementation** (meme discipline que
    `object_remap.py`/`core.services.expr`, deja appliquee dans ce projet) :
    - le cout matiere reutilise TEL QUEL `apps.mrp.services.bom.explode()`
      (RG-MRP-2/3/4 : eclatement multiniveau, chute, tailles), la MEME
      fonction pure qu'utilise `orders.confirm_order()` pour materialiser
      les `MrpOrderComponent.qty_planned` d'un ordre reel — jamais une
      resommation `line.qty * qty` divergente de l'arithmetique reelle ;
    - la formule frais generaux/total (`overhead = labor * rate/100`,
      `total = material + labor + overhead`) est IDENTIQUE a
      `compute_planned_cost` ci-dessus.

    **Cout facon** : ne peut PAS reutiliser `_labor_cost()` (qui lit les
    `MrpWorkOrder.duration_planned_min` d'un ordre deja confirme — cf.
    `orders.create_work_order()`, duree saisie manuellement a la creation
    de l'OF, jamais derivee automatiquement de la gamme) puisqu'aucun ordre
    n'existe encore en simulation. A la place, derive directement des
    `MrpRoutingStep.duration_min` de la gamme rattachee a la BOM
    (`bom.routing`), mis a l'echelle au prorata de `qty / bom.qty`
    (`bom.qty` = quantite de reference de la nomenclature) — meme structure
    de calcul que `_labor_cost` (heures * `workcenter.cost_per_hour_mga`),
    seule la source de la duree change. Si la BOM n'a pas de gamme
    rattachee (`routing` NULL), le cout facon simule est `Decimal(0)`
    (jamais une exception — coherent avec la discipline "jamais de faux
    positif" du reste de `mrp`), a charge de l'appelant (`feasibility`) de
    completer manuellement le `cost_breakdown` de son etude dans ce cas.

    N'ecrit RIEN, ne cree AUCUN `MrpOrder`/`MrpOrderComponent`/
    `MrpWorkOrder` — un simple dict de `Decimal`, teste explicitement
    (`test_costing.py::test_simulate_bom_cost_does_not_persist_anything`)."""
    material = Decimal(0)
    for row in explode(bom, qty):
        unit_cost = component_unit_costs.get(row["component_template_id"], Decimal(0))
        material += row["qty"] * unit_cost

    labor = Decimal(0)
    if bom.routing is not None and bom.qty:
        scale = qty / bom.qty
        for step in bom.routing.steps.select_related("workcenter").all():
            hours = (Decimal(step.duration_min) * scale) / Decimal(60)
            labor += hours * step.workcenter.cost_per_hour_mga

    overhead = labor * overhead_rate_pct / Decimal(100)
    total = material + labor + overhead
    return {"material": material, "labor": labor, "overhead": overhead, "total": total}


def compute_real_cost(
    order: MrpOrder, *, component_unit_costs: dict[UUID, Decimal], overhead_rate_pct: Decimal
) -> dict[str, Any]:
    """A n'appeler qu'a la cloture (RG-MRP-6). Le cout facon reel derive
    des seuls CRA `validated` (test d'acceptance n°4 : un CRA non valide
    n'entre pas dans le cout reel) — jamais de la duree brute saisie sur
    l'ordre de travail, cf. `services/cra.py::real_labor_cost()`."""
    material = _material_cost(
        order, qty_field="qty_consumed", component_unit_costs=component_unit_costs
    )
    labor = real_labor_cost(order)
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
            _("Un motif est obligatoire : l'écart de consommation depasse le seuil autorise.")
        )

    component.qty_consumed = qty_consumed
    component.variance_reason = reason
    component.state = "consumed"
    component.save(update_fields=["qty_consumed", "variance_reason", "state"])
    return component
