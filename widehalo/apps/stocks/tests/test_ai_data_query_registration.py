"""GW3 : adaptateur `apps.stocks.services.ai_data_query_registration` —
verifie l'enregistrement dans le registre partage et que le tool enveloppe
bien `stock_state_rows` sans reimplementation."""

from __future__ import annotations

import pytest

from apps.core.models.tenant import Tenant
from apps.core.services.data_query_tool_registry import get_data_query_tool
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.stocks.services.ai_data_query_registration import _tool_stock_state_rows

pytestmark = pytest.mark.django_db


def test_stock_state_rows_tool_is_registered() -> None:
    tool = get_data_query_tool("stocks.stock_state_rows")
    assert tool is not None
    assert tool.module == "stocks"
    assert tool.required_permission == "stocks.view_stkmove"
    assert tool.function is _tool_stock_state_rows


def test_stock_state_rows_tool_wraps_the_real_report_function() -> None:
    tenant = Tenant.objects.create(code="STOCKS-GW3-1", name="Stocks GW3 Tenant 1")
    user = UserFactory()
    with use_tenant(tenant.id):
        rows = _tool_stock_state_rows(tenant, user)
    assert isinstance(rows, list)
