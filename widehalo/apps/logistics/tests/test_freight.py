from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.logistics.services.freight import (
    compare_freight_tariffs,
    create_freight_tariff,
    create_service_provider,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return Tenant.objects.create(code="LOG-FRT-T", name="Logistics Freight Tenant")


def test_compare_freight_tariffs_ranks_by_cost_then_transit_days(tenant) -> None:
    with use_tenant(tenant.id):
        provider_a = create_service_provider(tenant, code="TRA", name="Transporteur A")
        provider_b = create_service_provider(tenant, code="TRB", name="Transporteur B")

        create_freight_tariff(
            provider_a,
            origin="Antananarivo",
            destination="Toamasina",
            price_mga=Decimal("100000"),
            transit_days=3,
        )
        create_freight_tariff(
            provider_b,
            origin="Antananarivo",
            destination="Toamasina",
            price_mga=Decimal("80000"),
            transit_days=5,
        )

        results = compare_freight_tariffs(tenant, origin="Antananarivo", destination="Toamasina")

        assert [r["provider_name"] for r in results] == ["Transporteur B", "Transporteur A"]


def test_compare_freight_tariffs_includes_weight_based_component(tenant) -> None:
    with use_tenant(tenant.id):
        provider = create_service_provider(tenant, code="TRC", name="Transporteur C")
        create_freight_tariff(
            provider,
            origin="Antananarivo",
            destination="Fianarantsoa",
            price_mga=Decimal("20000"),
            price_per_kg_mga=Decimal("500"),
            transit_days=1,
        )

        results = compare_freight_tariffs(
            tenant, origin="Antananarivo", destination="Fianarantsoa", weight_kg=Decimal("10")
        )

        assert results[0]["total_cost_mga"] == Decimal("25000")


def test_compare_freight_tariffs_excludes_expired_tariffs(tenant) -> None:
    with use_tenant(tenant.id):
        provider = create_service_provider(tenant, code="TRD", name="Transporteur D")
        create_freight_tariff(
            provider,
            origin="Antananarivo",
            destination="Mahajanga",
            price_mga=Decimal("60000"),
            transit_days=2,
            valid_to=dt.date(2020, 1, 1),
        )

        results = compare_freight_tariffs(tenant, origin="Antananarivo", destination="Mahajanga")

        assert results == []
