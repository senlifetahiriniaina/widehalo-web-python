from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.core.tests.factories import TenantFactory, UserFactory
from apps.core.tests.utils import grant_role, use_tenant
from apps.mrp.tests.factories import MrpCraFactory, MrpWorkshopFactory
from apps.presence.models import PrsOvertime
from apps.presence.services.attendance import check_in, check_out
from apps.presence.services.employees import create_employee
from apps.presence.services.overtime import record_overtime, validate_overtime
from apps.presence.services.public import get_validated_overtime_hours
from apps.presence.services.reconciliation import reconcile_month

pytestmark = pytest.mark.django_db


def test_record_and_validate_overtime() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        employee = create_employee(
            tenant, first_name="Rina", last_name="Rakoto", hire_date=dt.date(2026, 1, 1)
        )
        chef = UserFactory(email="chef@example.com")
        grant_role(chef, "rh")
        overtime = record_overtime(
            employee,
            date=dt.date(2026, 3, 2),
            hours=Decimal("2"),
            rate_category=PrsOvertime.RATE_H_SUP_30,
        )
        assert overtime.state == PrsOvertime.STATE_DRAFT
        validated = validate_overtime(overtime, chef)
        assert validated.state == PrsOvertime.STATE_VALIDATED

        total = get_validated_overtime_hours(
            tenant, employee.id, date_from=dt.date(2026, 3, 1), date_to=dt.date(2026, 3, 31)
        )
        assert total == Decimal("2")


def test_reconcile_month_flags_large_deviation() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        user = UserFactory(email="ouvrier@example.com")
        employee = create_employee(
            tenant, first_name="Rina", last_name="Rakoto", hire_date=dt.date(2026, 1, 1), user=user
        )
        at_in = dt.datetime(2026, 3, 2, 8, 0, tzinfo=dt.UTC)
        attendance = check_in(employee, mode="web", at=at_in)
        check_out(attendance, at=dt.datetime(2026, 3, 2, 17, 0, tzinfo=dt.UTC))

        workshop = MrpWorkshopFactory(tenant=tenant)
        MrpCraFactory(
            tenant=tenant,
            employee=user,
            workshop=workshop,
            date=dt.date(2026, 3, 2),
            hours=Decimal("1"),
            state="validated",
        )

        report = reconcile_month(tenant, employee, year=2026, month=3)
        assert report["flagged"] is True
        assert report["cra_hours"] == Decimal("1")


def test_reconcile_month_without_cra_data_is_not_blocking() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        employee = create_employee(
            tenant, first_name="Toky", last_name="Rasoa", hire_date=dt.date(2026, 1, 1)
        )
        report = reconcile_month(tenant, employee, year=2026, month=3)
        assert report["presence_hours"] == Decimal("0.00")
        assert report["cra_hours"] == Decimal(0)
