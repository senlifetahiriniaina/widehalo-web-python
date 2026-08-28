"""Factories factory_boy pour les modeles du module `stocks` (ST1) — meme
discipline que `apps.purchase.tests.factories`."""

from __future__ import annotations

import factory

from apps.stocks.models import StkDefectType, StkLocation, StkWarehouse


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
