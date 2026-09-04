"""A2 (L4 Agro) : généalogie de lot (`StkLotGenealogy`,
`services/genealogy.py`) — même idiome que `test_lot_dlc.py`/
`test_traceability.py` déjà présents pour A1."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLot, StkLotGenealogy
from apps.stocks.services.genealogy import genealogy_tree, record_consumption

pytestmark = pytest.mark.django_db


def test_record_consumption_creates_a_link_and_is_idempotent() -> None:
    tenant = Tenant.objects.create(code="GEN-1", name="Genealogy Tenant 1")
    with use_tenant(tenant.id):
        parent = StkLot.objects.create(tenant=tenant, variant_id=uuid.uuid4(), name="MP-001")
        child = StkLot.objects.create(tenant=tenant, variant_id=uuid.uuid4(), name="PF-001")

        record_consumption(
            tenant=tenant,
            parent_lot=parent,
            child_lot=child,
            qty=Decimal("10"),
            source_document="MRP-OF-2026-0001",
        )
        # meme cle (parent, enfant, source_document) => mise a jour, pas duplication
        record_consumption(
            tenant=tenant,
            parent_lot=parent,
            child_lot=child,
            qty=Decimal("15"),
            source_document="MRP-OF-2026-0001",
        )

        assert child.parent_links.count() == 1
        assert child.parent_links.first().qty == Decimal("15")


def test_genealogy_tree_reports_ancestors_and_descendants() -> None:
    tenant = Tenant.objects.create(code="GEN-2", name="Genealogy Tenant 2")
    with use_tenant(tenant.id):
        raw = StkLot.objects.create(tenant=tenant, variant_id=uuid.uuid4(), name="MP-100")
        finished = StkLot.objects.create(tenant=tenant, variant_id=uuid.uuid4(), name="PF-100")
        record_consumption(
            tenant=tenant,
            parent_lot=raw,
            child_lot=finished,
            qty=Decimal("5"),
            source_document="MRP-OF-2026-0002",
        )

        tree_from_child = genealogy_tree(finished)
        assert tree_from_child["ancestors"][0]["lot_name"] == "MP-100"
        assert tree_from_child["ancestors"][0]["qty"] == Decimal("5")

        tree_from_parent = genealogy_tree(raw)
        assert tree_from_parent["descendants"][0]["lot_name"] == "PF-100"


def test_genealogy_tree_has_no_links_for_an_isolated_lot() -> None:
    tenant = Tenant.objects.create(code="GEN-3", name="Genealogy Tenant 3")
    with use_tenant(tenant.id):
        lot = StkLot.objects.create(tenant=tenant, variant_id=uuid.uuid4(), name="ISO-1")
        tree = genealogy_tree(lot)
        assert tree["ancestors"] == []
        assert tree["descendants"] == []


def _brute_force_descendant_names(tenant: Tenant, lot: StkLot) -> set[str]:
    """Parcours BFS INDÉPENDANT (jamais `genealogy_tree` lui-même) — QUA-5
    (Bloc D, D4) : la bidirectionnalité récursive n'avait jamais été
    comparée à un recalcul brut. Requête directement `StkLotGenealogy`
    plutôt que d'appeler `genealogy_tree`, pour que ce test échoue
    réellement si l'implémentation récursive dérive un jour."""
    visited: set[str] = set()
    frontier = [lot.id]
    while frontier:
        children = StkLotGenealogy.objects.filter(
            tenant=tenant, parent_lot_id__in=frontier
        ).select_related("child_lot")
        next_frontier = []
        for link in children:
            if link.child_lot.name not in visited:
                visited.add(link.child_lot.name)
                next_frontier.append(link.child_lot_id)
        frontier = next_frontier
    return visited


def test_genealogy_tree_descendants_match_independent_brute_force_traversal() -> None:
    """QUA-5 : graphe à embranchements multiples — un lot racine consommé
    par deux lots enfants, l'un des deux ré-consommé par un troisième."""
    tenant = Tenant.objects.create(code="GEN-4", name="Genealogy Tenant 4")
    with use_tenant(tenant.id):
        root = StkLot.objects.create(tenant=tenant, variant_id=uuid.uuid4(), name="ROOT")
        branch_a = StkLot.objects.create(tenant=tenant, variant_id=uuid.uuid4(), name="BRANCH-A")
        branch_b = StkLot.objects.create(tenant=tenant, variant_id=uuid.uuid4(), name="BRANCH-B")
        leaf = StkLot.objects.create(tenant=tenant, variant_id=uuid.uuid4(), name="LEAF")
        record_consumption(
            tenant=tenant,
            parent_lot=root,
            child_lot=branch_a,
            qty=Decimal("10"),
            source_document="OF-1",
        )
        record_consumption(
            tenant=tenant,
            parent_lot=root,
            child_lot=branch_b,
            qty=Decimal("5"),
            source_document="OF-2",
        )
        record_consumption(
            tenant=tenant,
            parent_lot=branch_a,
            child_lot=leaf,
            qty=Decimal("3"),
            source_document="OF-3",
        )

        def _flatten(nodes: list[dict]) -> set[str]:
            names: set[str] = set()
            for node in nodes:
                names.add(node["lot_name"])
                names |= _flatten(node["children"])
            return names

        via_genealogy_tree = _flatten(genealogy_tree(root)["descendants"])
        via_brute_force = _brute_force_descendant_names(tenant, root)

        assert via_genealogy_tree == via_brute_force == {"BRANCH-A", "BRANCH-B", "LEAF"}
