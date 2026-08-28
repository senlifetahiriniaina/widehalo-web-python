"""Tests RG-PUR-7 (importation) : drapeau `import_dossier_pending` sur
`PurOrder` et `apps/purchase/services/imports.py::
create_import_cost_batch_for_order`."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounting.models import AccLandedCostBatch
from apps.accounting.services.landed_costs import landed_cost_report
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.purchase.models import PurOrder
from apps.purchase.services.imports import create_import_cost_batch_for_order
from apps.purchase.services.orders import add_order_line, create_order

pytestmark = pytest.mark.django_db


@pytest.fixture
def imports_setup():
    tenant = Tenant.objects.create(code="PUR-IMP", name="Purchase Imports Tenant")
    with use_tenant(tenant.id):
        return tenant


def test_create_order_sets_import_dossier_pending_only_for_import_origins(
    imports_setup,
) -> None:
    tenant = imports_setup
    with use_tenant(tenant.id):
        local_order = create_order(
            tenant=tenant, partner_id=uuid.uuid4(), date=timezone.now().date()
        )
        assert local_order.import_dossier_pending is False

        for origin in (
            PurOrder.ORIGIN_IMPORT_CHINE,
            PurOrder.ORIGIN_IMPORT_AUTRE,
            PurOrder.ORIGIN_EN_LIGNE,
        ):
            order = create_order(
                tenant=tenant, partner_id=uuid.uuid4(), date=timezone.now().date(), origin=origin
            )
            assert order.import_dossier_pending is True


def test_create_import_cost_batch_for_order_refuses_local_order(imports_setup) -> None:
    tenant = imports_setup
    with use_tenant(tenant.id):
        order = create_order(
            tenant=tenant,
            partner_id=uuid.uuid4(),
            date=timezone.now().date(),
            origin=PurOrder.ORIGIN_LOCAL,
        )

        with pytest.raises(ValidationError):
            create_import_cost_batch_for_order(order, cost_components=[])


def test_create_import_cost_batch_for_order_succeeds_for_import_order(imports_setup) -> None:
    tenant = imports_setup
    with use_tenant(tenant.id):
        order = create_order(
            tenant=tenant,
            partner_id=uuid.uuid4(),
            date=timezone.now().date(),
            origin=PurOrder.ORIGIN_IMPORT_CHINE,
        )
        add_order_line(
            order,
            variant_id=uuid.uuid4(),
            description="Tissu",
            qty=Decimal(100),
            unit_price_mga=Decimal(5000),
        )

        batch_id = create_import_cost_batch_for_order(
            order, cost_components=[{"label": "Fret maritime", "amount_mga": Decimal("50000")}]
        )

        assert batch_id is not None
        batch = AccLandedCostBatch.objects.get(id=batch_id)
        assert batch.total_purchase_value_mga == Decimal("500000")

        report = landed_cost_report(batch)
        assert len(report) == 1
        assert report[0]["description"] == "Tissu"
        assert report[0]["allocated_cost_mga"] == Decimal("50000")
        assert report[0]["landed_total_mga"] == Decimal("550000")


def test_create_import_cost_batch_for_order_returns_none_without_lines(imports_setup) -> None:
    tenant = imports_setup
    with use_tenant(tenant.id):
        order = create_order(
            tenant=tenant,
            partner_id=uuid.uuid4(),
            date=timezone.now().date(),
            origin=PurOrder.ORIGIN_IMPORT_CHINE,
        )

        batch_id = create_import_cost_batch_for_order(order, cost_components=[])

        assert batch_id is None
        assert not AccLandedCostBatch.objects.exists()
