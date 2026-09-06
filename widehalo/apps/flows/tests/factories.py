"""Factories du hub de flux.

Toute sous-factory tenant-scopee HERITE du tenant parent
(`factory.SelfAttribute("..tenant")`), convention du depot etablie par
`apps/catalog/tests/factories.py`. Sans elle, la sous-factory cree son
PROPRE tenant et la Row-Level Security rejette l'insertion sous le contexte
du parent — c'est exactement ce qui s'est produit au premier jet de ce
fichier, et l'erreur (`new row violates row-level security policy`) ne
designe pas la cause.

Une garde du depot (`apps/core/tests/test_tenant_portability_per_entity.py`)
exige une factory par modele heritant de `BaseModel` : sans elle, un test de
portabilite ne peut pas construire l'entite et l'oublie en silence.
"""

from __future__ import annotations

import datetime as dt

import factory

from apps.core.tests.factories import TenantFactory
from apps.flows.models import (
    FlwConnector,
    FlwCredential,
    FlwExchange,
    FlwIncident,
    FlwLink,
    FlwMapping,
    FlwPayload,
    FlwSchedule,
    FlwTrigger,
)


class FlwConnectorFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FlwConnector

    tenant = factory.SubFactory(TenantFactory)
    code = factory.Sequence(lambda n: f"connecteur-{n}")
    name = "Connecteur de test"
    family = FlwConnector.FAMILY_FISCAL
    supported_operations = factory.List(["OP1"])


class FlwCredentialFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FlwCredential

    tenant = factory.SubFactory(TenantFactory)
    connector = factory.SubFactory(FlwConnectorFactory, tenant=factory.SelfAttribute("..tenant"))
    label = "Identifiant de test"
    kind = FlwCredential.KIND_API_KEY
    secret = "secret-de-test"


class FlwLinkFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FlwLink

    tenant = factory.SubFactory(TenantFactory)
    connector = factory.SubFactory(FlwConnectorFactory, tenant=factory.SelfAttribute("..tenant"))
    name = factory.Sequence(lambda n: f"liaison-{n}")


class FlwMappingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FlwMapping

    tenant = factory.SubFactory(TenantFactory)
    link = factory.SubFactory(FlwLinkFactory, tenant=factory.SelfAttribute("..tenant"))
    document_type = "facture_vente"


class FlwScheduleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FlwSchedule

    tenant = factory.SubFactory(TenantFactory)
    link = factory.SubFactory(FlwLinkFactory, tenant=factory.SelfAttribute("..tenant"))
    operation = "OP1"
    frequency = FlwSchedule.FREQUENCY_DAILY


class FlwTriggerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FlwTrigger

    tenant = factory.SubFactory(TenantFactory)
    link = factory.SubFactory(FlwLinkFactory, tenant=factory.SelfAttribute("..tenant"))
    event_name = "sales.order_confirmed"
    operation = "OP1"


class FlwExchangeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FlwExchange

    tenant = factory.SubFactory(TenantFactory)
    link = factory.SubFactory(FlwLinkFactory, tenant=factory.SelfAttribute("..tenant"))
    direction = FlwExchange.DIRECTION_OUTBOUND
    operation = "OP1"
    partition_month = factory.LazyFunction(lambda: dt.date.today().replace(day=1))


class FlwPayloadFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FlwPayload

    tenant = factory.SubFactory(TenantFactory)
    exchange = factory.SubFactory(FlwExchangeFactory, tenant=factory.SelfAttribute("..tenant"))
    body = '{"exemple": true}'


class FlwIncidentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FlwIncident

    tenant = factory.SubFactory(TenantFactory)
    link = factory.SubFactory(FlwLinkFactory, tenant=factory.SelfAttribute("..tenant"))
    family = FlwIncident.FAMILY_UNAVAILABLE
    state = FlwIncident.STATE_OPEN
    first_seen_at = factory.LazyFunction(lambda: dt.datetime.now(tz=dt.UTC))
    last_seen_at = factory.LazyFunction(lambda: dt.datetime.now(tz=dt.UTC))
