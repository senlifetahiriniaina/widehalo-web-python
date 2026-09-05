"""Bloc F, F1 (Phase 3 §13.2, « besoin matière prévisionnel via
nomenclature ») : explosion des prévisions de vente
(`apps.sales.SalesForecast` — PAS `apps.forecast.ForSeriesForecast`,
une prévision de VALEUR par famille/article/client/canal sans notion de
nomenclature, cf. docstring `apps/forecast/models.py`, qui reporte
explicitement « la prévision de besoins matière » à cette Phase 3) à
travers les nomenclatures de production (`apps.mrp`), confrontée à
l'état courant du stock/réservations (`apps.stocks`) et des commandes
fournisseur déjà en cours (`apps.purchase`). Aucun critère FOR-x
numéroté ne ferme ce sprint (recherche exhaustive : aucun n'existe dans
le plan ni l'audit Phase 3 pour « besoin matière ») — seul le texte
narratif de la ligne F1 du plan fait foi.

Aucun accès direct aux modèles d'autres apps (règle de couplage n°1) :
- `apps.sales.services.public.get_forecast_summary` (déjà existant) —
  demande prévue par variante/période.
- `apps.catalog.services.public.get_variant_template_id` (déjà
  existant) — le produit fini prévu vers son `ProductTemplate` (la
  nomenclature raisonne en template, jamais en variante).
- `apps.mrp.services.public.explode_material_needs` (NOUVEAU, ce
  sprint) — explosion de la nomenclature ACTIVE d'un template pour une
  quantité donnée.
- `apps.stocks.services.public.get_available_stock_qty` (déjà
  existant) — stock disponible, DÉJÀ NET des réservations
  (`qty - qty_reserved`, cf. `services.quants.available_qty`) : la
  confrontation aux réservations de l'énoncé F1 est donc couverte par
  ce même appel, jamais un second.
- `apps.purchase.services.public.get_open_order_qty` (NOUVEAU, ce
  sprint) — quantité restant à recevoir sur les commandes fournisseur
  EN COURS, déjà convertie dans l'unité de stock.

Portée assumée et disclosée : le rendement/les sous-produits d'une
nomenclature de type PROCESS (`MrpBom.expected_yield_pct`/
`by_products`, C5) ne sont PAS pris en compte ici — `explode()`
lui-même les ignore (purement déclaratif, consommé uniquement par la
réconciliation matière de C3), et ce sprint (5 JT) n'ajoute aucun
calcul de majoration supplémentaire : le besoin matière d'un produit de
type process reste une lecture brute de la nomenclature, pas un besoin
ajusté du rendement — écart documenté, pas silencieux. Un produit fini
prévu sans nomenclature active n'est pas décomposé (traité comme sans
composant à en déduire), jamais une erreur bloquante."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.catalog.services.public import get_variant_template_id
from apps.core.models.tenant import Tenant
from apps.mrp.services.public import explode_material_needs
from apps.purchase.services.public import get_open_order_qty
from apps.sales.services.public import get_forecast_summary
from apps.stocks.services.public import get_available_stock_qty


def compute_material_needs(
    tenant: Tenant, *, period_from: str, period_to: str
) -> list[dict[str, Any]]:
    """Besoin matière net par composant sur l'horizon
    `[period_from, period_to]` (périodes `"YYYY-MM"`, même format que
    `sales.SalesForecast.period`) : demande prévue de chaque produit
    fini agrégée sur l'horizon, explosée via sa nomenclature active,
    puis chaque composant confronté UNE SEULE FOIS (agrégé across tous
    les produits finis qui le consomment) au stock disponible et aux
    commandes fournisseur en cours."""
    demand_by_variant: dict[str, Decimal] = {}
    for row in get_forecast_summary(tenant, period_from=period_from, period_to=period_to):
        qty = row["qty_forecast"]
        if qty <= 0:
            continue
        demand_by_variant[row["variant_id"]] = (
            demand_by_variant.get(row["variant_id"], Decimal(0)) + qty
        )

    gross_needs: dict[str, Decimal] = {}
    for variant_id, forecast_qty in demand_by_variant.items():
        template_id = get_variant_template_id(variant_id)
        if template_id is None:
            continue
        exploded = explode_material_needs(template_id, forecast_qty)
        if exploded is None:
            continue
        for component in exploded:
            component_variant_id = component["component_variant_id"]
            if component_variant_id is None:
                continue
            key = str(component_variant_id)
            gross_needs[key] = gross_needs.get(key, Decimal(0)) + component["qty"]

    results: list[dict[str, Any]] = []
    for component_variant_id, gross_qty in gross_needs.items():
        available = get_available_stock_qty(component_variant_id)
        on_order = get_open_order_qty(component_variant_id)
        results.append(
            {
                "component_variant_id": component_variant_id,
                "gross_need": gross_qty,
                "available_stock": available,
                "on_order": on_order,
                "net_need": max(gross_qty - available - on_order, Decimal(0)),
            }
        )
    return sorted(results, key=lambda r: r["component_variant_id"])
