"""Bloc D, D1 : plan de contrôle + points critiques."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.quality.services.control_plans import (
    add_critical_point,
    create_control_plan,
    get_last_measurement_date,
)
from apps.quality.services.measurements import record_measurement
from apps.stocks.tests.factories import StkLotFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    t = Tenant.objects.create(code="QLT-CP", name="Quality Control Plan Tenant")
    with use_tenant(t.id):
        yield t


def test_create_control_plan_and_add_critical_point(tenant) -> None:
    with use_tenant(tenant.id):
        plan = create_control_plan(tenant=tenant, name="Réception matière", frequency_days=7)
        point = add_critical_point(
            plan, name="pH", unit="", limit_min=Decimal("4.0"), limit_max=Decimal("4.6")
        )
        assert point.control_plan_id == plan.id
        assert plan.critical_points.count() == 1


def test_critical_point_with_only_upper_bound(tenant) -> None:
    with use_tenant(tenant.id):
        plan = create_control_plan(tenant=tenant, name="Stockage froid")
        point = add_critical_point(plan, name="Température", unit="°C", limit_max=Decimal("4"))
        assert point.limit_min is None
        assert point.limit_max == Decimal("4")


def test_get_last_measurement_date_is_none_without_measurement(tenant) -> None:
    with use_tenant(tenant.id):
        plan = create_control_plan(tenant=tenant, name="Cuisson")
        point = add_critical_point(plan, name="Température", limit_min=Decimal(70))
        lot = StkLotFactory(tenant=tenant, name="LOT-CP-001")
        assert (
            get_last_measurement_date(point, lot_variant_id=lot.variant_id, lot_name=lot.name)
            is None
        )


def test_get_last_measurement_date_reflects_latest_measurement(tenant) -> None:
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="cp@example.com", password="Str0ngPassw0rd!23")
        plan = create_control_plan(tenant=tenant, name="Cuisson")
        point = add_critical_point(
            plan, name="Température", limit_min=Decimal(70), limit_max=Decimal(90)
        )
        lot = StkLotFactory(tenant=tenant, name="LOT-CP-002")

        measurement = record_measurement(
            point,
            tenant=tenant,
            value=Decimal(80),
            measured_by=user,
            lot_variant_id=lot.variant_id,
            lot_name=lot.name,
        )

        last_date = get_last_measurement_date(
            point, lot_variant_id=lot.variant_id, lot_name=lot.name
        )
        assert last_date == measurement.measured_at
