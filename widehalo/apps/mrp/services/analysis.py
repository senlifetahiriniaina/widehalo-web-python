"""MRP-CONSO1 (composants partages/consolidation d'achats) et MRP-WHERE1
(analyse d'impact « ou est utilise ce composant »)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.core.models.tenant import Tenant
from apps.mrp.models import MrpBom

MAX_WHERE_USED_DEPTH = 5


def find_shared_components(tenant: Tenant) -> list[dict[str, Any]]:
    """MRP-CONSO1 : composants references par plus d'une nomenclature
    active — candidats a une commande groupee."""
    usage: dict[UUID, set[UUID]] = {}
    for bom in MrpBom.objects.filter(tenant=tenant, state=MrpBom.STATE_ACTIVE).prefetch_related(
        "lines"
    ):
        for line in bom.lines.all():
            usage.setdefault(line.component_template_id, set()).add(bom.product_template_id)

    return [
        {"component_template_id": component_id, "used_in_products": sorted(products, key=str)}
        for component_id, products in usage.items()
        if len(products) > 1
    ]


def where_used(tenant: Tenant, component_template_id: UUID) -> list[UUID]:
    """MRP-WHERE1 : recherche recursive ascendante — tous les produits finis
    (racines de nomenclature) affectes, directement ou indirectement, par
    un changement de ce composant."""
    affected: set[UUID] = set()
    _walk_up(tenant, component_template_id, affected, depth=1)
    return sorted(affected, key=str)


def _walk_up(tenant: Tenant, component_template_id: UUID, affected: set[UUID], depth: int) -> None:
    if depth > MAX_WHERE_USED_DEPTH:
        return

    parent_boms = MrpBom.objects.filter(
        tenant=tenant, state=MrpBom.STATE_ACTIVE, lines__component_template_id=component_template_id
    ).distinct()
    for parent_bom in parent_boms:
        affected.add(parent_bom.product_template_id)
        _walk_up(tenant, parent_bom.product_template_id, affected, depth + 1)
