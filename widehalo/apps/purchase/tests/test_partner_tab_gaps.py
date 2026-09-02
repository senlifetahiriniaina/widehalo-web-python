"""Tests du gap PT5 (chantier "fiche partenaire a onglets par role") sur
le contrat public de `purchase` : `list_orders_for_partner`."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant
from apps.purchase.services.public import list_orders_for_partner
from apps.purchase.tests.factories import PurOrderFactory

pytestmark = pytest.mark.django_db


def test_list_orders_for_partner_returns_rows_ordered_by_date_desc() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        partner_id = uuid.uuid4()
        older = PurOrderFactory(tenant=tenant, partner_id=partner_id, date=dt.date(2026, 1, 1))
        newer = PurOrderFactory(tenant=tenant, partner_id=partner_id, date=dt.date(2026, 2, 1))
        PurOrderFactory(tenant=tenant)  # other partner, must not appear

        rows = list_orders_for_partner(partner_id)

        assert [row["id"] for row in rows] == [newer.id, older.id]
        assert rows[0]["reference"] == newer.reference
        assert rows[0]["state"] == newer.state
        assert rows[0]["total"] == newer.amount_total_mga


def test_list_orders_for_partner_returns_empty_list_for_unknown_partner() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        assert list_orders_for_partner(uuid.uuid4()) == []


def test_list_orders_for_partner_respects_limit() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        partner_id = uuid.uuid4()
        for _ in range(3):
            PurOrderFactory(tenant=tenant, partner_id=partner_id)

        rows = list_orders_for_partner(partner_id, limit=2)

        assert len(rows) == 2
