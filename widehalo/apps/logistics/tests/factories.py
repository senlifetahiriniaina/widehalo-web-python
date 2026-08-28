"""Factories factory_boy pour les modeles du module `logistics` (LOG1) —
meme discipline que `apps.purchase.tests.factories`/`apps.stocks.tests.factories`."""

from __future__ import annotations

import datetime as dt
import uuid

import factory
from django.contrib.contenttypes.models import ContentType

from apps.logistics.models import (
    LogDriver,
    LogFreightTariff,
    LogPackagingPlan,
    LogPackagingPlanLine,
    LogPackagingType,
    LogServiceProvider,
    LogShipment,
    LogShipmentLeg,
    LogTrip,
    LogTripStop,
    LogTripTemplate,
    LogVehicle,
    LogVehicleCost,
    LogVehicleDocument,
)


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


class LogTripFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LogTrip

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    vehicle = factory.SubFactory(LogVehicleFactory, tenant=factory.SelfAttribute("..tenant"))
    driver = factory.SubFactory(LogDriverFactory, tenant=factory.SelfAttribute("..tenant"))
    date = factory.LazyFunction(dt.date.today)
    reference = factory.Sequence(lambda n: f"TRJ-{n}")


class LogTripStopFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LogTripStop

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    trip = factory.SubFactory(LogTripFactory, tenant=factory.SelfAttribute("..tenant"))
    sequence = factory.Sequence(lambda n: n + 1)
    address = factory.Sequence(lambda n: f"Adresse {n}")


class LogTripTemplateFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LogTripTemplate

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Gabarit {n}")
    vehicle = factory.SubFactory(LogVehicleFactory, tenant=factory.SelfAttribute("..tenant"))
    driver = factory.SubFactory(LogDriverFactory, tenant=factory.SelfAttribute("..tenant"))
    interval = LogTripTemplate.INTERVAL_WEEKLY
    stops_data = factory.LazyFunction(lambda: [{"address": "Depot"}])
    next_run = factory.LazyFunction(dt.date.today)


class LogPackagingTypeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LogPackagingType

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"CTN-{n}")
    name = factory.Sequence(lambda n: f"Carton {n}")
    tare_weight_kg = 1


class LogPackagingPlanFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LogPackagingPlan

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    reference = factory.Sequence(lambda n: f"PLN-{n}")

    # Meme convention que `apps.core.tests.factories` (ex. `ApprovalRequestFactory`) :
    # une reference generique OPAQUE (UUID pendant, jamais un objet reellement
    # cree dans le meme tenant) — sinon le round-trip d'export/import (T3)
    # remappe cette reference vers le nouvel id reimporte, ce qui casserait
    # l'hypothese par defaut du test parametrique generique.
    content_type = factory.LazyFunction(lambda: ContentType.objects.get_for_model(LogTrip))
    object_id = factory.LazyFunction(lambda: str(uuid.uuid4()))


class LogPackagingPlanLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LogPackagingPlanLine

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    plan = factory.SubFactory(LogPackagingPlanFactory, tenant=factory.SelfAttribute("..tenant"))
    packaging_type = factory.SubFactory(
        LogPackagingTypeFactory, tenant=factory.SelfAttribute("..tenant")
    )
    variant_id = factory.Faker("uuid4")
    qty_units = 12
    qty_packages = 1


class LogServiceProviderFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LogServiceProvider

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"PRV-{n}")
    name = factory.Sequence(lambda n: f"Transporteur {n}")


class LogFreightTariffFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LogFreightTariff

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    provider = factory.SubFactory(
        LogServiceProviderFactory, tenant=factory.SelfAttribute("..tenant")
    )
    origin = "Antananarivo"
    destination = "Toamasina"
    price_mga = 50000
    transit_days = 2


class LogShipmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LogShipment

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    reference = factory.Sequence(lambda n: f"SHP-{n}")
    origin = "Guangzhou"
    destination = "Antananarivo"


class LogShipmentLegFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LogShipmentLeg

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    shipment = factory.SubFactory(LogShipmentFactory, tenant=factory.SelfAttribute("..tenant"))
    sequence = factory.Sequence(lambda n: n + 1)
    origin = "Guangzhou"
    destination = "Toamasina"
