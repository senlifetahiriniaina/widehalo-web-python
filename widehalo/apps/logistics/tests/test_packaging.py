from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.catalog.models import Packaging, ProductTemplate, ProductVariant, UnitOfMeasure
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.logistics.services.packaging import compute_packaging_plan
from apps.logistics.services.trips import create_trip
from apps.logistics.services.vehicles import create_driver, create_vehicle

pytestmark = pytest.mark.django_db


@pytest.fixture
def packaging_setup():
    tenant = Tenant.objects.create(code="LOG-PKG-T", name="Logistics Packaging Tenant")
    with use_tenant(tenant.id):
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PC", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )
        template = ProductTemplate.objects.create(
            tenant=tenant, name="Tissu", base_uom=uom, base_price_mga=Decimal("1000")
        )
        variant = ProductVariant.objects.create(tenant=tenant, template=template)
        Packaging.objects.create(tenant=tenant, variant=variant, unit_count=12, uom=uom)

        from apps.logistics.models import LogPackagingType

        packaging_type = LogPackagingType.objects.create(
            tenant=tenant,
            code="CTN-STD",
            name="Carton standard",
            tare_weight_kg=Decimal("1.5"),
            volume_m3=Decimal("0.05"),
        )

        vehicle = create_vehicle(tenant, plate_number="7777 TBA")
        driver = create_driver(tenant, name="Rasoa")
        trip = create_trip(
            tenant,
            vehicle=vehicle,
            driver=driver,
            date=__import__("datetime").date.today(),
            stops=[{"address": "Client A"}],
        )
        return tenant, variant, packaging_type, trip


def test_compute_packaging_plan_rounds_up_to_full_packages(packaging_setup) -> None:
    tenant, variant, packaging_type, trip = packaging_setup
    with use_tenant(tenant.id):
        plan = compute_packaging_plan(
            tenant,
            source=trip,
            packaging_type=packaging_type,
            lines=[{"variant_id": variant.id, "qty": Decimal("25")}],
        )
        line = plan.lines.first()
        assert line.qty_packages == 3  # 25 unites / 12 par carton -> 3 cartons
        assert plan.total_weight_kg == Decimal("4.5")
        assert plan.total_volume_m3 == Decimal("0.15")


def test_compute_packaging_plan_requires_declared_packaging(packaging_setup) -> None:
    tenant, _variant, packaging_type, trip = packaging_setup
    with use_tenant(tenant.id):
        import uuid

        with pytest.raises(ValidationError):
            compute_packaging_plan(
                tenant,
                source=trip,
                packaging_type=packaging_type,
                lines=[{"variant_id": uuid.uuid4(), "qty": Decimal("5")}],
            )


def test_compute_packaging_plan_requires_at_least_one_line(packaging_setup) -> None:
    tenant, _variant, packaging_type, trip = packaging_setup
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        compute_packaging_plan(tenant, source=trip, packaging_type=packaging_type, lines=[])
