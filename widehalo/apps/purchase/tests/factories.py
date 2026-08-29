"""Factories factory_boy pour les modeles du module `purchase` (PU1,
demande d'achat) — meme discipline que `apps.sales.tests.factories`.

`tenant` est resolu via un `SubFactory` a chemin pointe vers
`apps.core.tests.factories.TenantFactory` (resolution paresseuse, meme
patron que `apps.sales.tests.factories`). `variant_id`/`preferred_supplier_id`
sont toujours de simples UUID (jamais de FK Django vers `apps.catalog`/
`apps.partners` — regle de couplage n1)."""

from __future__ import annotations

import datetime as dt
import uuid

import factory
from django.utils import timezone

from apps.purchase.models import (
    PrcPriceSnapshot,
    PrcPriceWatchTarget,
    PurCra,
    PurCri,
    PurOrder,
    PurOrderLine,
    PurReceiptLine,
    PurReorderingRule,
    PurRequisition,
    PurRequisitionLine,
    PurRfq,
    PurRfqLine,
    PurRfqResponse,
    PurRfqResponseLine,
    PurRfqSupplier,
    PurSubstitute,
)


class PurRequisitionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PurRequisition

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    requester = factory.SubFactory("apps.core.tests.factories.UserFactory")
    date_needed = factory.LazyFunction(dt.date.today)


class PurRequisitionLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PurRequisitionLine

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    requisition = factory.SubFactory(
        PurRequisitionFactory, tenant=factory.SelfAttribute("..tenant")
    )
    variant_id = factory.LazyFunction(uuid.uuid4)
    description = factory.Sequence(lambda n: f"Ligne {n}")
    qty = 1


class PurSubstituteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PurSubstitute

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    variant_id = factory.LazyFunction(uuid.uuid4)
    substitute_variant_id = factory.LazyFunction(uuid.uuid4)
    compatibility = PurSubstitute.COMPATIBILITY_EQUIVALENT


class PurRfqFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PurRfq

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    date = factory.LazyFunction(dt.date.today)


class PurRfqLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PurRfqLine

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    rfq = factory.SubFactory(PurRfqFactory, tenant=factory.SelfAttribute("..tenant"))
    variant_id = factory.LazyFunction(uuid.uuid4)
    description = factory.Sequence(lambda n: f"Ligne RFQ {n}")
    qty = 1


class PurRfqSupplierFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PurRfqSupplier

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    rfq = factory.SubFactory(PurRfqFactory, tenant=factory.SelfAttribute("..tenant"))
    partner_id = factory.LazyFunction(uuid.uuid4)


class PurRfqResponseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PurRfqResponse

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    rfq = factory.SubFactory(PurRfqFactory, tenant=factory.SelfAttribute("..tenant"))
    partner_id = factory.LazyFunction(uuid.uuid4)
    date_received = factory.LazyFunction(dt.date.today)


class PurRfqResponseLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PurRfqResponseLine

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    response = factory.SubFactory(PurRfqResponseFactory, tenant=factory.SelfAttribute("..tenant"))
    variant_id = factory.LazyFunction(uuid.uuid4)
    qty = 1
    unit_price_mga = 1000


class PurOrderFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PurOrder

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    partner_id = factory.LazyFunction(uuid.uuid4)
    date = factory.LazyFunction(dt.date.today)


class PurOrderLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PurOrderLine

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    order = factory.SubFactory(PurOrderFactory, tenant=factory.SelfAttribute("..tenant"))
    variant_id = factory.LazyFunction(uuid.uuid4)
    description = factory.Sequence(lambda n: f"Ligne commande {n}")
    qty = 1
    unit_price_mga = 1000


class PurReceiptLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PurReceiptLine

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    order_line = factory.SubFactory(PurOrderLineFactory, tenant=factory.SelfAttribute("..tenant"))
    qty_received = 1
    quality_status = PurReceiptLine.QUALITY_CONFORME


class PurReorderingRuleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PurReorderingRule

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    variant_id = factory.LazyFunction(uuid.uuid4)
    min_qty = 10
    max_qty = 50


class PurCraFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PurCra

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    buyer = factory.SubFactory("apps.core.tests.factories.UserFactory")
    date = factory.LazyFunction(dt.date.today)
    partner_id = factory.LazyFunction(uuid.uuid4)
    activity_type = PurCra.TYPE_SOURCING
    hours = 1


class PurCriFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PurCri

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    date = factory.LazyFunction(dt.date.today)
    type = PurCri.TYPE_RETARD
    partner_id = factory.LazyFunction(uuid.uuid4)
    description = factory.Sequence(lambda n: f"Incident {n}")


class PrcPriceWatchTargetFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PrcPriceWatchTarget

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    platform_code = PrcPriceWatchTarget.PLATFORM_ALIBABA
    search_query_or_url = factory.Sequence(lambda n: f"tissu coton 200g/m2 #{n}")
    currency = "MGA"
    frequency = PrcPriceWatchTarget.FREQUENCY_MONTHLY
    variant_id = factory.LazyFunction(uuid.uuid4)


class PrcPriceSnapshotFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PrcPriceSnapshot

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    target = factory.SubFactory(
        PrcPriceWatchTargetFactory, tenant=factory.SelfAttribute("..tenant")
    )
    observed_price = 1000
    observed_at = factory.LazyFunction(timezone.now)
    is_stub = True
