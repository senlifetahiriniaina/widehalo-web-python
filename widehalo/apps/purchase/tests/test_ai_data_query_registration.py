"""INT2 : `services.ai_data_query_registration` — tool `purchase.supplier_
risk_scores`, enveloppe directe de `apps.mrp.services.public.get_supplier_
score` (RG-PUR-8, deja consomme par `purchase` depuis PU7)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.core.services.data_query_tool_registry import get_data_query_tool
from apps.core.tests.factories import TenantFactory, UserFactory
from apps.core.tests.utils import use_tenant
from apps.mrp.services.public import record_supplier_evaluation
from apps.purchase.services.ai_data_query_registration import _tool_supplier_risk_scores
from apps.purchase.tests.factories import PurOrderFactory

pytestmark = pytest.mark.django_db


def test_tool_is_registered_in_the_shared_registry() -> None:
    tool = get_data_query_tool("purchase.supplier_risk_scores")
    assert tool is not None
    assert tool.module == "purchase"
    assert tool.required_permission == "purchase.view_purorder"
    assert tool.function is _tool_supplier_risk_scores


def test_tool_returns_empty_list_for_tenant_without_data() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        user = UserFactory()
        rows = _tool_supplier_risk_scores(tenant, user)

    assert rows == []


def test_tool_skips_a_supplier_without_any_evaluation() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        user = UserFactory()
        PurOrderFactory(tenant=tenant)

        rows = _tool_supplier_risk_scores(tenant, user)

    assert rows == []


def test_tool_returns_the_latest_score_of_an_evaluated_supplier() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        user = UserFactory()
        order = PurOrderFactory(tenant=tenant)
        record_supplier_evaluation(
            tenant=tenant,
            partner_id=order.partner_id,
            date=dt.date.today(),
            score_quantity=Decimal(4),
            score_quality=Decimal(4),
            score_cost=Decimal(4),
            score_delay=Decimal(4),
            score_conformity=Decimal(4),
        )

        rows = _tool_supplier_risk_scores(tenant, user)

    assert len(rows) == 1
    assert rows[0]["partner_id"] == str(order.partner_id)
    assert Decimal(rows[0]["weighted_score"]) == Decimal("80.00")


def test_tool_filters_by_risk_threshold() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        user = UserFactory()
        order = PurOrderFactory(tenant=tenant)
        record_supplier_evaluation(
            tenant=tenant,
            partner_id=order.partner_id,
            date=dt.date.today(),
            score_quantity=Decimal(4),
            score_quality=Decimal(4),
            score_cost=Decimal(4),
            score_delay=Decimal(4),
            score_conformity=Decimal(4),
        )

        rows = _tool_supplier_risk_scores(tenant, user, risk_threshold=50.0)

    assert rows == []
