from __future__ import annotations

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLocation, StkWarehouse
from apps.stocks.services.defaults import ensure_unqualified_location

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(code="STK-QUALIF-T", name="Stocks Qualif Tenant")


def test_ensure_unqualified_location_creates_a_virtual_location(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        warehouse = StkWarehouse.objects.create(
            tenant=tenant, code="WH-Q1", name="Entrepot qualif", type=StkWarehouse.TYPE_PRINCIPAL
        )
        location = ensure_unqualified_location(warehouse)
        assert location.type == StkLocation.TYPE_INVENTAIRE
        assert location.code == "ZONE-A-QUALIFIER"


def test_ensure_unqualified_location_is_idempotent_per_warehouse(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        warehouse = StkWarehouse.objects.create(
            tenant=tenant, code="WH-Q2", name="Entrepot qualif 2", type=StkWarehouse.TYPE_PRINCIPAL
        )
        first = ensure_unqualified_location(warehouse)
        second = ensure_unqualified_location(warehouse)
        count = StkLocation.objects.filter(warehouse=warehouse, code="ZONE-A-QUALIFIER").count()
        assert first.id == second.id
        assert count == 1


def test_ensure_unqualified_location_is_distinct_per_warehouse(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        warehouse_a = StkWarehouse.objects.create(
            tenant=tenant, code="WH-QA", name="Entrepot A", type=StkWarehouse.TYPE_PRINCIPAL
        )
        warehouse_b = StkWarehouse.objects.create(
            tenant=tenant, code="WH-QB", name="Entrepot B", type=StkWarehouse.TYPE_PRINCIPAL
        )
        location_a = ensure_unqualified_location(warehouse_a)
        location_b = ensure_unqualified_location(warehouse_b)
        assert location_a.id != location_b.id
