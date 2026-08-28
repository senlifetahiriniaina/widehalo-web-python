"""Factories factory_boy pour les modeles du module `presence`."""

from __future__ import annotations

import datetime as dt

import factory

from apps.presence.models import (
    PrsAbsence,
    PrsAbsenceType,
    PrsAttendance,
    PrsDepartment,
    PrsEmployee,
    PrsLeaveBalance,
    PrsOvertime,
    PrsWorkCalendar,
)

_DEFAULT_DAYS = {
    day: [["08:00", "12:00"], ["14:00", "17:00"]] for day in ("mon", "tue", "wed", "thu", "fri")
}


class PrsDepartmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PrsDepartment

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"DEP-{n}")
    name = factory.Sequence(lambda n: f"Departement {n}")


class PrsWorkCalendarFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PrsWorkCalendar

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Calendrier {n}")
    days = factory.LazyFunction(lambda: dict(_DEFAULT_DAYS))


class PrsEmployeeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PrsEmployee

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    reference = factory.Sequence(lambda n: f"PRS-2026-{n:04d}")
    first_name = factory.Sequence(lambda n: f"Prenom{n}")
    last_name = factory.Sequence(lambda n: f"Nom{n}")
    hire_date = factory.LazyFunction(lambda: dt.date(2024, 1, 1))


class PrsAttendanceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PrsAttendance

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    employee = factory.SubFactory(PrsEmployeeFactory, tenant=factory.SelfAttribute("..tenant"))
    date = factory.LazyFunction(lambda: dt.date(2026, 1, 6))
    mode = PrsAttendance.MODE_WEB


class PrsAbsenceTypeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PrsAbsenceType

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"ABS-{n}")
    name = factory.Sequence(lambda n: f"Type absence {n}")
    category = PrsAbsenceType.CATEGORY_PAID_LEAVE


class PrsAbsenceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PrsAbsence

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    reference = factory.Sequence(lambda n: f"ABSREF-{n:04d}")
    employee = factory.SubFactory(PrsEmployeeFactory, tenant=factory.SelfAttribute("..tenant"))
    type = factory.SubFactory(PrsAbsenceTypeFactory, tenant=factory.SelfAttribute("..tenant"))
    date_from = factory.LazyFunction(lambda: dt.date(2026, 1, 6))
    date_to = factory.LazyFunction(lambda: dt.date(2026, 1, 6))
    days_count = 1


class PrsLeaveBalanceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PrsLeaveBalance

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    employee = factory.SubFactory(PrsEmployeeFactory, tenant=factory.SelfAttribute("..tenant"))
    year = 2026
    type = factory.SubFactory(PrsAbsenceTypeFactory, tenant=factory.SelfAttribute("..tenant"))


class PrsOvertimeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PrsOvertime

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    employee = factory.SubFactory(PrsEmployeeFactory, tenant=factory.SelfAttribute("..tenant"))
    date = factory.LazyFunction(lambda: dt.date(2026, 1, 6))
    hours = 2
    rate_category = PrsOvertime.RATE_H_SUP_30
