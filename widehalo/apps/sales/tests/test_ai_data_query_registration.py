"""GW3 : adaptateurs `apps.sales.services.ai_data_query_registration` —
verifie l'enregistrement dans le registre partage et que `sales.margin_
report` passe bien les roles REELS de l'utilisateur (RG-SAL-5), jamais un
role code en dur ni un ensemble elargi."""

from __future__ import annotations

import datetime as dt

import pytest

from apps.core.models.tenant import Tenant
from apps.core.services.data_query_tool_registry import get_data_query_tool
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.sales.services.ai_data_query_registration import (
    _tool_margin_report,
    _tool_revenue_report,
)
from apps.sales.tests.factories import SalesOrderLineFactory

pytestmark = pytest.mark.django_db


def test_revenue_report_tool_is_registered() -> None:
    tool = get_data_query_tool("sales.revenue_report")
    assert tool is not None
    assert tool.module == "sales"
    assert tool.required_permission == "sales.view_salesorder"
    assert tool.function is _tool_revenue_report


def test_margin_report_tool_is_registered() -> None:
    tool = get_data_query_tool("sales.margin_report")
    assert tool is not None
    assert tool.module == "sales"
    assert tool.required_permission == "sales.view_salesorder"
    assert tool.function is _tool_margin_report


def test_revenue_report_tool_wraps_the_real_report_function() -> None:
    tenant = Tenant.objects.create(code="SALES-GW3-1", name="Sales GW3 Tenant 1")
    user = UserFactory()
    with use_tenant(tenant.id):
        SalesOrderLineFactory(tenant=tenant, qty=1, unit_price=100)
        rows = _tool_revenue_report(
            tenant, user, date_from="2000-01-01", date_to=dt.date.today().isoformat()
        )
    assert isinstance(rows, list)


def test_margin_report_tool_masks_margin_for_a_role_without_visibility() -> None:
    """RG-SAL-5 : un utilisateur sans role autorise (`commercial` seul, ni
    `direction`/`admin`/`resp_commercial`) ne recoit jamais `margin_pct`/
    `cost_estimate_mga` — meme masquage que `_adapter_margin_report`
    (export classique)."""
    from django.contrib.auth.models import Group

    tenant = Tenant.objects.create(code="SALES-GW3-2", name="Sales GW3 Tenant 2")
    user = UserFactory()
    group, _created = Group.objects.get_or_create(name="commercial")
    user.groups.add(group)
    with use_tenant(tenant.id):
        SalesOrderLineFactory(tenant=tenant, qty=1, unit_price=100, margin_pct=20)
        rows = _tool_margin_report(tenant, user)
    assert rows
    assert "margin_pct" not in rows[0]


def test_margin_report_tool_reveals_margin_for_a_role_with_visibility() -> None:
    from django.contrib.auth.models import Group

    tenant = Tenant.objects.create(code="SALES-GW3-3", name="Sales GW3 Tenant 3")
    user = UserFactory()
    group, _created = Group.objects.get_or_create(name="direction")
    user.groups.add(group)
    with use_tenant(tenant.id):
        SalesOrderLineFactory(tenant=tenant, qty=1, unit_price=100, margin_pct=20)
        rows = _tool_margin_report(tenant, user)
    assert rows
    assert "margin_pct" in rows[0]
