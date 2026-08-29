"""Tests du contrat public de `sales` (`apps/sales/services/public.py`) —
seule surface que `stocks`/`purchase`/`payroll`/`reporting`/`strategy` ont
le droit d'importer. Couvre `get_quotation_reference`/`get_order_reference`
(deja existants) et le gap ajoute par `stocks` ST6 (RG-STK-6) :
`get_delivered_qty_for_order`."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.sales.services.public import (
    get_delivered_qty_for_order,
    get_forecast_summary,
    get_order_reference,
    get_quotation_reference,
)
from apps.sales.tests.factories import (
    SalesForecastFactory,
    SalesOrderFactory,
    SalesOrderLineFactory,
    SalesQuotationFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def public_setup():
    tenant = Tenant.objects.create(code="SAL-PUB", name="Sales Public Tenant")
    with use_tenant(tenant.id):
        return tenant


def test_get_quotation_reference_returns_reference(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        quotation = SalesQuotationFactory(tenant=tenant, reference="DEVIS-1")
        assert get_quotation_reference(quotation.id) == "DEVIS-1"


def test_get_quotation_reference_returns_empty_for_unknown(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        assert get_quotation_reference(uuid.uuid4()) == ""


def test_get_order_reference_returns_reference(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        order = SalesOrderFactory(tenant=tenant, reference="CMD-1")
        assert get_order_reference(order.id) == "CMD-1"


def test_get_delivered_qty_for_order_sums_all_lines(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        order = SalesOrderFactory(tenant=tenant)
        SalesOrderLineFactory(tenant=tenant, order=order, qty_delivered=Decimal("3"))
        SalesOrderLineFactory(tenant=tenant, order=order, qty_delivered=Decimal("2"))

        assert get_delivered_qty_for_order(order.id) == Decimal("5")


def test_get_delivered_qty_for_order_returns_zero_without_lines(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        order = SalesOrderFactory(tenant=tenant)
        assert get_delivered_qty_for_order(order.id) == Decimal(0)


def test_get_delivered_qty_for_order_returns_none_for_unknown_order(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        assert get_delivered_qty_for_order(uuid.uuid4()) is None


def test_get_forecast_summary_filters_by_period_range(public_setup) -> None:
    """Nouveau gap ajoute pendant le chantier `strategy` (rapport business
    plan)."""
    tenant = public_setup
    with use_tenant(tenant.id):
        SalesForecastFactory(tenant=tenant, period="2026-06", qty_forecast=Decimal("100"))
        SalesForecastFactory(tenant=tenant, period="2026-07", qty_forecast=Decimal("200"))

        rows = get_forecast_summary(tenant, period_from="2026-06", period_to="2026-06")

        assert len(rows) == 1
        assert rows[0]["period"] == "2026-06"
        assert rows[0]["qty_forecast"] == Decimal("100")
