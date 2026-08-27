"""Factories factory_boy pour les modeles du module `mrp` — une par modele
concret (couche T1 du plan de durcissement, CDC §14 couches).

`tenant` est resolu via un `SubFactory` a chemin pointe vers
`apps.core.tests.factories.TenantFactory` (resolution paresseuse,
fonctionne meme si ce module est ecrit en parallele par un autre agent).
Meme convention pour `employee`/`declared_by` (FK `core.User`) via
`apps.core.tests.factories.UserFactory`.

`product_template_id`/`variant_id`/`component_template_id`/`partner_id`
sont toujours de simples UUID (jamais de FK Django vers
`apps.catalog`/`apps.partners` — regle de couplage n°1).

`MrpOrder.state`, `MrpCra.state` et `MrpBomLineState.state` sont des
`FSMField` : on ne les instancie jamais via une methode `@transition`, on
laisse la valeur par defaut ("draft"/"a_commander") s'appliquer."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import factory

from apps.mrp.models import (
    MrpBom,
    MrpBomLine,
    MrpBomLineState,
    MrpCra,
    MrpCri,
    MrpMaintenancePlan,
    MrpOperation,
    MrpOrder,
    MrpOrderComponent,
    MrpRouting,
    MrpRoutingStep,
    MrpSampleRequest,
    MrpScrap,
    MrpSubcontractOrder,
    MrpSupplierEvaluation,
    MrpWorkcenter,
    MrpWorkOrder,
    MrpWorkshop,
)


class MrpWorkshopFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MrpWorkshop

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"ATL{n}")
    name = factory.Sequence(lambda n: f"Atelier {n}")


class MrpWorkcenterFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MrpWorkcenter

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    workshop = factory.SubFactory(MrpWorkshopFactory, tenant=factory.SelfAttribute("..tenant"))
    code = factory.Sequence(lambda n: f"WC{n}")
    name = factory.Sequence(lambda n: f"Poste {n}")
    type = MrpWorkcenter.TYPE_SEWING


class MrpOperationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MrpOperation

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"OP{n}")
    name = factory.Sequence(lambda n: f"Operation {n}")
    workcenter_type = MrpWorkcenter.TYPE_SEWING


class MrpRoutingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MrpRouting

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"RT{n}")
    name = factory.Sequence(lambda n: f"Gamme {n}")
    product_template_id = factory.LazyFunction(uuid.uuid4)


class MrpRoutingStepFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MrpRoutingStep

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    routing = factory.SubFactory(MrpRoutingFactory, tenant=factory.SelfAttribute("..tenant"))
    operation = factory.SubFactory(MrpOperationFactory, tenant=factory.SelfAttribute("..tenant"))
    workcenter = factory.SubFactory(MrpWorkcenterFactory, tenant=factory.SelfAttribute("..tenant"))
    sequence = factory.Sequence(lambda n: n)
    duration_min = 30


class MrpBomFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MrpBom

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"BOM{n}")
    product_template_id = factory.LazyFunction(uuid.uuid4)
    type = MrpBom.TYPE_MANUFACTURE
    qty = Decimal("1.0000")
    # `state` reste "draft" (valeur par defaut) — la validation
    # anti-cycle/versioning (RG-MRP) vit dans `mrp.services.bom`, jamais
    # dans une factory de test.


class MrpBomLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MrpBomLine

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    bom = factory.SubFactory(MrpBomFactory, tenant=factory.SelfAttribute("..tenant"))
    component_template_id = factory.LazyFunction(uuid.uuid4)
    qty = Decimal("1.0000")


class MrpOrderFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MrpOrder

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    variant_id = factory.LazyFunction(uuid.uuid4)
    qty = Decimal("1.0000")
    bom = factory.SubFactory(MrpBomFactory, tenant=factory.SelfAttribute("..tenant"))
    workshop = factory.SubFactory(MrpWorkshopFactory, tenant=factory.SelfAttribute("..tenant"))
    # `state` (FSMField) reste "draft" — jamais de methode @transition
    # appelee depuis une factory.


class MrpOrderComponentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MrpOrderComponent

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    order = factory.SubFactory(MrpOrderFactory, tenant=factory.SelfAttribute("..tenant"))
    bom_line = factory.SubFactory(MrpBomLineFactory, tenant=factory.SelfAttribute("..tenant"))
    qty_planned = Decimal("1.0000")


class MrpWorkOrderFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MrpWorkOrder

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    order = factory.SubFactory(MrpOrderFactory, tenant=factory.SelfAttribute("..tenant"))
    workcenter = factory.SubFactory(MrpWorkcenterFactory, tenant=factory.SelfAttribute("..tenant"))
    sequence = factory.Sequence(lambda n: n)
    qty_planned = Decimal("1.0000")


class MrpSubcontractOrderFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MrpSubcontractOrder

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    order = factory.SubFactory(MrpOrderFactory, tenant=factory.SelfAttribute("..tenant"))
    partner_id = factory.LazyFunction(uuid.uuid4)
    qty = Decimal("1.0000")


class MrpCraFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MrpCra

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    date = datetime.date(2026, 1, 15)
    employee = factory.SubFactory("apps.core.tests.factories.UserFactory")
    workshop = factory.SubFactory(MrpWorkshopFactory, tenant=factory.SelfAttribute("..tenant"))
    hours = Decimal("8.00")
    # `state` (FSMField) reste "draft" — jamais de methode @transition
    # appelee depuis une factory.


class MrpCriFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MrpCri

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    date = datetime.date(2026, 1, 15)
    type = MrpCri.TYPE_MAINTENANCE
    workcenter = factory.SubFactory(MrpWorkcenterFactory, tenant=factory.SelfAttribute("..tenant"))


class MrpScrapFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MrpScrap

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    order = factory.SubFactory(MrpOrderFactory, tenant=factory.SelfAttribute("..tenant"))
    qty = Decimal("1.0000")
    reason = factory.Sequence(lambda n: f"Rebut {n}")
    date = datetime.date(2026, 1, 15)
    declared_by = factory.SubFactory("apps.core.tests.factories.UserFactory")


class MrpBomLineStateFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MrpBomLineState

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    order_component = factory.SubFactory(
        MrpOrderComponentFactory, tenant=factory.SelfAttribute("..tenant")
    )
    # `state` (FSMField) reste "a_commander" — jamais de methode
    # @transition appelee depuis une factory.


class MrpSupplierEvaluationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MrpSupplierEvaluation

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    partner_id = factory.LazyFunction(uuid.uuid4)
    date = datetime.date(2026, 1, 15)


class MrpSampleRequestFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MrpSampleRequest

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    partner_id = factory.LazyFunction(uuid.uuid4)
    component_template_id = factory.LazyFunction(uuid.uuid4)
    date_requested = datetime.date(2026, 1, 15)


class MrpMaintenancePlanFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MrpMaintenancePlan

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    workcenter = factory.SubFactory(MrpWorkcenterFactory, tenant=factory.SelfAttribute("..tenant"))
    name = factory.Sequence(lambda n: f"Plan de maintenance {n}")
    trigger_type = MrpMaintenancePlan.TRIGGER_CALENDAR
    interval_days = 90
