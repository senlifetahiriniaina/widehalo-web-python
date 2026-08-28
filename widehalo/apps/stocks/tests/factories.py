"""Factories factory_boy pour les modeles du module `stocks` (ST1+ST2) —
meme discipline que `apps.purchase.tests.factories`."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import factory

from apps.stocks.models import (
    StkDefectType,
    StkLocation,
    StkLot,
    StkMove,
    StkQuant,
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
