from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant
from apps.presence.models import PrsAttendance
from apps.presence.services.attendance import check_in, check_out, manual_entry
from apps.presence.services.employees import create_employee, create_work_calendar
from apps.presence.services.retention import purge_expired_geolocation

pytestmark = pytest.mark.django_db


def _make_employee(tenant, calendar=None):
    return create_employee(
        tenant,
        first_name="Rina",
        last_name="Rakoto",
        hire_date=dt.date(2026, 1, 1),
        work_calendar=calendar,
    )


def test_check_in_out_computes_worked_minutes() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        calendar = create_work_calendar(
            tenant, name="Standard", days={"tue": [["08:00", "12:00"], ["14:00", "17:00"]]}
        )
        employee = _make_employee(tenant, calendar=calendar)
        at_in = timezone.make_aware(dt.datetime(2026, 1, 6, 8, 0))
        attendance = check_in(employee, mode=PrsAttendance.MODE_WEB, at=at_in)
        at_out = timezone.make_aware(dt.datetime(2026, 1, 6, 17, 30))
        attendance = check_out(attendance, at=at_out)
        assert attendance.worked_minutes == 9 * 60 + 30
        assert attendance.overtime_minutes == 30


def test_out_of_perimeter_checkin_is_recorded_not_rejected() -> None:
    """Test d'acceptance §5.9.8 n°1 : un pointage hors périmètre
    géographique est enregistré mais signalé."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        employee = _make_employee(tenant)
        attendance = check_in(
            employee,
            mode=PrsAttendance.MODE_MOBILE,
            latitude=Decimal("-18.9"),
            longitude=Decimal("47.5"),
            site_latitude=Decimal("-18.879"),
            site_longitude=Decimal("47.507"),
            radius_meters=200,
        )
        assert attendance.pk is not None
        assert attendance.within_perimeter is False


def test_manual_entry_requires_reason() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        employee = _make_employee(tenant)
        with pytest.raises(ValidationError):
            manual_entry(
                employee,
                date=dt.date(2026, 1, 6),
                check_in=timezone.make_aware(dt.datetime(2026, 1, 6, 8, 0)),
                check_out=None,
                entered_by=employee.created_by,
                reason="   ",
            )


def test_geolocation_purged_after_30_days_keeps_within_perimeter() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        employee = _make_employee(tenant)
        attendance = check_in(
            employee,
            mode=PrsAttendance.MODE_MOBILE,
            latitude=Decimal("-18.879"),
            longitude=Decimal("47.507"),
            site_latitude=Decimal("-18.879"),
            site_longitude=Decimal("47.507"),
            radius_meters=200,
        )
        attendance.geo_captured_at = timezone.now() - dt.timedelta(days=31)
        attendance.save(update_fields=["geo_captured_at"])

        purged = purge_expired_geolocation()
        assert purged == 1
        attendance.refresh_from_db()
        assert attendance.latitude is None
        assert attendance.longitude is None
        assert attendance.within_perimeter is True
