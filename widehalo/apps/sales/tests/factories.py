"""Factories factory_boy pour les modeles du module `sales` (S1 devis, S2
commande de vente) — couche T1 du plan de durcissement, CDC §14 couches.

`tenant` est resolu via un `SubFactory` a chemin pointe vers
`apps.core.tests.factories.TenantFactory` (resolution paresseuse, meme
patron que `apps.crm.tests.factories`). `partner_id`/`variant_id` sont
toujours de simples UUID (jamais de FK Django vers `apps.partners`/
`apps.catalog` — regle de couplage n1)."""

from __future__ import annotations

import datetime as dt
import uuid

import factory

from apps.sales.models import (
    SalesCustomerCalendar,
    SalesForecast,
    SalesOrder,
    SalesOrderLine,
    SalesQuotation,
    SalesQuotationLine,
    SalesRecurrence,
    SalesTarget,
)


class SalesQuotationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SalesQuotation

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    partner_id = factory.LazyFunction(uuid.uuid4)
    date = factory.LazyFunction(dt.date.today)


class SalesQuotationLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SalesQuotationLine

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    quotation = factory.SubFactory(SalesQuotationFactory, tenant=factory.SelfAttribute("..tenant"))
    variant_id = factory.LazyFunction(uuid.uuid4)
    description = factory.Sequence(lambda n: f"Ligne {n}")
    qty = 1


class SalesOrderFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SalesOrder

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    partner_id = factory.LazyFunction(uuid.uuid4)
    date = factory.LazyFunction(dt.date.today)


class SalesOrderLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SalesOrderLine

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    order = factory.SubFactory(SalesOrderFactory, tenant=factory.SelfAttribute("..tenant"))
    variant_id = factory.LazyFunction(uuid.uuid4)
    description = factory.Sequence(lambda n: f"Ligne {n}")
    qty = 1


class SalesRecurrenceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SalesRecurrence

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Recurrence {n}")
    interval = SalesRecurrence.INTERVAL_MONTHLY
    start_date = factory.LazyFunction(dt.date.today)
    next_run = factory.LazyFunction(dt.date.today)
    template_order = factory.SubFactory(SalesOrderFactory, tenant=factory.SelfAttribute("..tenant"))


class SalesCustomerCalendarFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SalesCustomerCalendar

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    partner_id = factory.LazyFunction(uuid.uuid4)
    label = factory.Sequence(lambda n: f"Evenement {n}")
    date_from = factory.LazyFunction(dt.date.today)
    date_to = factory.LazyFunction(dt.date.today)
    type = SalesCustomerCalendar.TYPE_CLOSURE
    impact_pct = -100


class SalesTargetFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SalesTarget

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    period = "2026-01"
    scope = SalesTarget.SCOPE_COMPANY
    amount_mga = 0


class SalesForecastFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SalesForecast

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    period = "2026-01"
    variant_id = factory.LazyFunction(uuid.uuid4)
    qty_forecast = 0
    confidence = SalesForecast.CONFIDENCE_LOW
    method = "weighted_moving_average+exponential_smoothing"
