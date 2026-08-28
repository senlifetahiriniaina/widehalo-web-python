"""Factories factory_boy pour les modeles du module `logistics` (LOG1) —
meme discipline que `apps.purchase.tests.factories`/`apps.stocks.tests.factories`."""

from __future__ import annotations

import datetime as dt

import factory

from apps.logistics.models import LogDriver, LogVehicle, LogVehicleCost, LogVehicleDocument


class LogVehicleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LogVehicle

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    plate_number = factory.Sequence(lambda n: f"PLT-{n}")
    type = LogVehicle.TYPE_TRUCK


class LogVehicleDocumentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LogVehicleDocument

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    vehicle = factory.SubFactory(LogVehicleFactory, tenant=factory.SelfAttribute("..tenant"))
    doc_type = LogVehicleDocument.TYPE_INSURANCE


class LogVehicleCostFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LogVehicleCost

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    vehicle = factory.SubFactory(LogVehicleFactory, tenant=factory.SelfAttribute("..tenant"))
    date = factory.LazyFunction(dt.date.today)
    cost_type = LogVehicleCost.TYPE_FUEL
    amount_mga = 10000


class LogDriverFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LogDriver

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Chauffeur {n}")
