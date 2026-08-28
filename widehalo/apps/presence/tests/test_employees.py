from __future__ import annotations

import datetime as dt

import pytest

from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant
from apps.presence.models import PrsEmployee
from apps.presence.services.employees import (
    create_department,
    create_employee,
    create_work_calendar,
    terminate_employee,
)

pytestmark = pytest.mark.django_db


def test_create_employee_assigns_sequenced_reference() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        employee = create_employee(
            tenant, first_name="Rina", last_name="Rakoto", hire_date=dt.date(2026, 1, 5)
        )
        assert employee.reference.startswith("PRS-2026-")
        second = create_employee(
            tenant, first_name="Toky", last_name="Rasoa", hire_date=dt.date(2026, 2, 1)
        )
        assert second.reference != employee.reference


def test_department_hierarchy_and_manager() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        parent = create_department(tenant, code="DG", name="Direction générale")
        child = create_department(tenant, code="RH", name="Ressources humaines", parent=parent)
        assert child.parent_id == parent.id


def test_work_calendar_days_json() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        calendar = create_work_calendar(tenant, name="Standard", days={"mon": [["08:00", "17:00"]]})
        assert calendar.days["mon"] == [["08:00", "17:00"]]


def test_terminate_employee_rejects_end_date_before_hire() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        employee = create_employee(
            tenant, first_name="Rina", last_name="Rakoto", hire_date=dt.date(2026, 1, 5)
        )
        with pytest.raises(Exception):  # noqa: B017 — ValidationError Django
            terminate_employee(employee, end_date=dt.date(2025, 1, 1))


def test_cin_is_encrypted_at_rest() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        employee = create_employee(
            tenant,
            first_name="Rina",
            last_name="Rakoto",
            hire_date=dt.date(2026, 1, 5),
            cin="101012345678",
        )
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT cin FROM prs_employee WHERE id = %s", [str(employee.id)])
            raw_value = cursor.fetchone()[0]
        assert raw_value != "101012345678"
        assert PrsEmployee.objects.get(id=employee.id).cin == "101012345678"
