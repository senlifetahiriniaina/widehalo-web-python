"""A2 (L4 Agro) : généalogie de lot (`StkLotGenealogy`,
`services/genealogy.py`) — même idiome que `test_lot_dlc.py`/
`test_traceability.py` déjà présents pour A1."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLot
from apps.stocks.services.genealogy import genealogy_tree, record_consumption

pytestmark = pytest.mark.django_db


def test_record_consumption_creates_a_link_and_is_idempotent() -> None:
    tenant = Tenant.objects.create(code="GEN-1", name="Genealogy Tenant 1")
    with use_tenant(tenant.id):
        parent = StkLot.objects.create(tenant=tenant, variant_id=uuid.uuid4(), name="MP-001")
        child = StkLot.objects.create(tenant=tenant, variant_id=uuid.uuid4(), name="PF-001")

        record_consumption(
            tenant=tenant, parent_lot=parent, child_lot=child, qty=Decimal("10"),
            source_document="MRP-OF-2026-0001",
        )
        # meme cle (parent, enfant, source_document) => mise a jour, pas duplication
        record_consumption(
            tenant=tenant, parent_lot=parent, child_lot=child, qty=Decimal("15"),
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
            tenant=tenant, parent_lot=raw, child_lot=finished, qty=Decimal("5"),
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
