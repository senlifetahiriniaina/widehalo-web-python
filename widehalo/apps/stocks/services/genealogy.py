"""A2 (L4 Agro) : généalogie de lot — enregistrement et lecture des liens
parent(s)/enfant entre lots (`StkLotGenealogy`), distincts de la
traçabilité mouvement-par-mouvement d'un seul lot (`services/
traceability.py`, qui reste inchangé et continue de couvrir le besoin A1).

Lecture en arbre (`genealogy_tree`) plutôt qu'une simple liste à plat :
un lot de produit fini peut avoir plusieurs parents (plusieurs matières
premières consommées), et un lot de matière première peut nourrir
plusieurs lots enfants (plusieurs ordres de transformation successifs) —
l'écran A3 (rappel produit) a besoin de remonter TOUS les lots finis
impactés par un lot suspect, donc de la profondeur, pas seulement du
premier niveau."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.core.models.tenant import Tenant
from apps.stocks.models import StkLot, StkLotGenealogy

# Garde-fou anti-cycle/anti-explosion, même discipline que
# `apps.mrp.services.bom.explode` (profondeur max 5) — une chaîne de
# transformation agro réaliste (matière première -> semi-fini -> fini)
# ne dépasse pas quelques niveaux.
MAX_DEPTH = 10


def record_consumption(
    *,
    tenant: Tenant,
    parent_lot: StkLot,
    child_lot: StkLot,
    qty: Decimal,
    source_document: str = "",
) -> StkLotGenealogy:
    """Enregistre qu'une quantité `qty` du `parent_lot` a été consommée
    pour produire le `child_lot`. Idempotent sur
    (parent_lot, child_lot, source_document) : un second appel avec les
    mêmes clés met à jour la quantité plutôt que de dupliquer la
    ligne (un ordre peut être rouvert/corrigé)."""
    link, _created = StkLotGenealogy.objects.update_or_create(
        tenant=tenant,
        parent_lot=parent_lot,
        child_lot=child_lot,
        source_document=source_document,
        defaults={"qty": qty},
    )
    return link


def genealogy_tree(lot: StkLot) -> dict[str, Any]:
    """Arbre de traçabilité amont (`ancestors`)/aval (`descendants`) du
    `lot` donné, jusqu'à `MAX_DEPTH` niveaux. Chaque nœud est un dict
    primitif `{"lot_id", "lot_name", "variant_id", "qty",
    "source_document", "children"/"parents": [...]}` — jamais un objet
    `StkLotGenealogy`/`StkLot` brut, pour rester consultable tel quel par
    un template sans dépendance au modèle."""
    return {
        "lot_id": lot.id,
        "lot_name": lot.name,
        "variant_id": lot.variant_id,
        "ancestors": _ancestors(lot, depth=0, seen={lot.id}),
        "descendants": _descendants(lot, depth=0, seen={lot.id}),
    }


def _ancestors(lot: StkLot, *, depth: int, seen: set[Any]) -> list[dict[str, Any]]:
    if depth >= MAX_DEPTH:
        return []
    nodes = []
    for link in lot.parent_links.select_related("parent_lot").all():
        parent = link.parent_lot
        if parent.id in seen:
            continue  # garde anti-cycle
        nodes.append(
            {
                "lot_id": parent.id,
                "lot_name": parent.name,
                "variant_id": parent.variant_id,
                "qty": link.qty,
                "source_document": link.source_document,
                "parents": _ancestors(parent, depth=depth + 1, seen=seen | {parent.id}),
            }
        )
    return nodes


def _descendants(lot: StkLot, *, depth: int, seen: set[Any]) -> list[dict[str, Any]]:
    if depth >= MAX_DEPTH:
        return []
    nodes = []
    for link in lot.child_links.select_related("child_lot").all():
        child = link.child_lot
        if child.id in seen:
            continue
        nodes.append(
            {
                "lot_id": child.id,
                "lot_name": child.name,
                "variant_id": child.variant_id,
                "qty": link.qty,
                "source_document": link.source_document,
                "children": _descendants(child, depth=depth + 1, seen=seen | {child.id}),
            }
        )
    return nodes
