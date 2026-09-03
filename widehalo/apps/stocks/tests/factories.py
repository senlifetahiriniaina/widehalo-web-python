"""Factories factory_boy pour les modeles du module `stocks` (ST1+ST2) —
meme discipline que `apps.purchase.tests.factories`."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import factory
from django.utils import timezone

from apps.stocks.models import (
    StkAbcClassification,
    StkDefectType,
    StkImportBatch,
    StkImportRow,
    StkInventory,
    StkInventoryLine,
    StkLocation,
    StkLot,
    StkLotGenealogy,
    StkMeasurement,
    StkMove,
    StkNegativeStockException,
    StkPicking,
    StkQualityState,
    StkQuant,
    StkRecall,
    StkReservation,
    StkReturn,
    StkValuationLayer,
    StkWarehouse,
)


class StkWarehouseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StkWarehouse

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"WH-{n}")
    name = factory.Sequence(lambda n: f"Entrepot {n}")
    type = StkWarehouse.TYPE_PRINCIPAL


class StkLocationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StkLocation

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    warehouse = factory.SubFactory(StkWarehouseFactory, tenant=factory.SelfAttribute("..tenant"))
    code = factory.Sequence(lambda n: f"LOC-{n}")
    name = factory.Sequence(lambda n: f"Emplacement {n}")
    type = StkLocation.TYPE_INTERNE


class StkDefectTypeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StkDefectType

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"DEF-{n}")
    name = factory.Sequence(lambda n: f"Defaut {n}")
    category = StkDefectType.CATEGORY_TISSU
    severity = StkDefectType.SEVERITY_MINEUR


class StkLotFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StkLot

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    variant_id = factory.LazyFunction(uuid.uuid4)
    name = factory.Sequence(lambda n: f"LOT-{n}")


class StkLotGenealogyFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StkLotGenealogy

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    parent_lot = factory.SubFactory(StkLotFactory, tenant=factory.SelfAttribute("..tenant"))
    child_lot = factory.SubFactory(StkLotFactory, tenant=factory.SelfAttribute("..tenant"))
    qty = Decimal("1")


class StkQuantFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StkQuant

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    variant_id = factory.LazyFunction(uuid.uuid4)
    location = factory.SubFactory(StkLocationFactory, tenant=factory.SelfAttribute("..tenant"))
    qty = Decimal("0")
    qty_reserved = Decimal("0")
    unit_cost_mga = Decimal("0")
    value_mga = Decimal("0")


class StkMoveFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StkMove

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    reference = factory.Sequence(lambda n: f"STKMV-{n}")
    variant_id = factory.LazyFunction(uuid.uuid4)
    qty = Decimal("1")
    uom = "pc"
    location_from = factory.SubFactory(StkLocationFactory, tenant=factory.SelfAttribute("..tenant"))
    location_to = factory.SubFactory(StkLocationFactory, tenant=factory.SelfAttribute("..tenant"))
    date = factory.LazyFunction(dt.date.today)
    state = StkMove.STATE_DRAFT
    move_type = StkMove.TYPE_TRANSFERT_INTERNE
    unit_cost_mga = Decimal("0")
    value_mga = Decimal("0")


class StkValuationLayerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StkValuationLayer

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    move = factory.SubFactory(StkMoveFactory, tenant=factory.SelfAttribute("..tenant"))
    variant_id = factory.LazyFunction(uuid.uuid4)
    qty = Decimal("1")
    unit_cost_mga = Decimal("0")
    value_mga = Decimal("0")
    remaining_qty = Decimal("1")
    remaining_value_mga = Decimal("0")
    date = factory.LazyFunction(dt.date.today)


class StkMeasurementFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StkMeasurement

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    type = StkMeasurement.TYPE_LONGUEUR
    value = Decimal("1")
    uom = "m"
    measured_at = factory.LazyFunction(timezone.now)


class StkPickingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StkPicking

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    reference = factory.Sequence(lambda n: f"STKPCK-{n}")
    type = StkPicking.TYPE_INTERNE
    location_from = factory.SubFactory(StkLocationFactory, tenant=factory.SelfAttribute("..tenant"))
    location_to = factory.SubFactory(StkLocationFactory, tenant=factory.SelfAttribute("..tenant"))
    state = StkPicking.STATE_DRAFT


class StkQualityStateFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StkQualityState

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    quant = factory.SubFactory(StkQuantFactory, tenant=factory.SelfAttribute("..tenant"))
    state = StkQualityState.STATE_CONFORME
    defect_qty = Decimal("0")


class StkReservationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StkReservation

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    quant = factory.SubFactory(StkQuantFactory, tenant=factory.SelfAttribute("..tenant"))
    qty = Decimal("1")
    date = factory.LazyFunction(dt.date.today)
    state = StkReservation.STATE_ACTIVE


class StkInventoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StkInventory

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    reference = factory.Sequence(lambda n: f"STKINV-{n}")
    warehouse = factory.SubFactory(StkWarehouseFactory, tenant=factory.SelfAttribute("..tenant"))
    date = factory.LazyFunction(dt.date.today)
    type = StkInventory.TYPE_PONCTUEL
    state = StkInventory.STATE_DRAFT


class StkInventoryLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StkInventoryLine

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    inventory = factory.SubFactory(StkInventoryFactory, tenant=factory.SelfAttribute("..tenant"))
    variant_id = factory.LazyFunction(uuid.uuid4)
    location = factory.SubFactory(StkLocationFactory, tenant=factory.SelfAttribute("..tenant"))
    qty_theoretical = Decimal("0")


class StkReturnFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StkReturn

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    reference = factory.Sequence(lambda n: f"STKRET-{n}")
    partner_id = factory.LazyFunction(uuid.uuid4)
    variant_id = factory.LazyFunction(uuid.uuid4)
    qty = Decimal("1")
    date = factory.LazyFunction(dt.date.today)
    state = StkReturn.STATE_DRAFT


class StkRecallFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StkRecall

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    reference = factory.Sequence(lambda n: f"RECALL-{n}")
    lot = factory.SubFactory(StkLotFactory, tenant=factory.SelfAttribute("..tenant"))
    reason = "Test"


class StkNegativeStockExceptionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StkNegativeStockException

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    variant_id = factory.LazyFunction(uuid.uuid4)
    authorized_by = factory.SubFactory("apps.core.tests.factories.UserFactory")
    reason = "Rupture temporaire acceptee"


class StkAbcClassificationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StkAbcClassification

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    variant_id = factory.LazyFunction(uuid.uuid4)
    abc_class = StkAbcClassification.CLASS_A
    consumption_value_mga = Decimal("0")
    computed_at = factory.LazyFunction(timezone.now)


class StkImportBatchFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StkImportBatch

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    kind = StkImportBatch.KIND_INITIAL_QUANTITIES
    format_version = 1


class StkImportRowFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StkImportRow

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    batch = factory.SubFactory(StkImportBatchFactory, tenant=factory.SelfAttribute("..tenant"))
    row_number = factory.Sequence(lambda n: n + 1)
