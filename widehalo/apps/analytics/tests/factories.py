"""Factories factory_boy pour les modèles du module `analytics`."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import factory
from django.utils import timezone

from apps.analytics.models import (
    AnDimArticle,
    AnDimTemps,
    AnDimTiers,
    AnFactEcriture,
    AnFactEncaissement,
    AnFactTicketPos,
    AnFactVente,
    AnMetricDefinition,
    AnRefreshRun,
    AnWarehouseState,
)


class AnDimTempsFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AnDimTemps

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    date = dt.date(2026, 9, 1)
    annee = 2026
    trimestre = 3
    mois = 9
    mois_libelle = "Septembre"
    semaine_iso = 36
    jour_du_mois = 1
    jour_semaine_iso = 2
    jour_semaine_libelle = "Mardi"
    est_weekend = False
    exercice_fiscal = 2026


class AnDimTiersFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AnDimTiers

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    partner_id = factory.LazyFunction(uuid.uuid4)
    code = factory.Sequence(lambda n: f"TIERS-{n}")
    nom = factory.Sequence(lambda n: f"Tiers {n}")


class AnDimArticleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AnDimArticle

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    variant_id = factory.LazyFunction(uuid.uuid4)
    reference = factory.Sequence(lambda n: f"ART-{n}")
    libelle = factory.Sequence(lambda n: f"Article {n}")


class AnFactVenteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AnFactVente

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    source_line_id = factory.LazyFunction(uuid.uuid4)
    dim_temps = factory.SubFactory(AnDimTempsFactory, tenant=factory.SelfAttribute("..tenant"))
    order_reference = "SO-0001"
    order_state = "confirmed"
    qty = Decimal("1")
    unit_price_mga = Decimal("10000")
    montant_ht_mga = Decimal("10000")


class AnFactTicketPosFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AnFactTicketPos

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    source_line_id = factory.LazyFunction(uuid.uuid4)
    dim_temps = factory.SubFactory(AnDimTempsFactory, tenant=factory.SelfAttribute("..tenant"))
    ticket_number = "CAISSE-1-000001"
    qty = Decimal("1")
    unit_price_mga = Decimal("5000")
    montant_ht_mga = Decimal("5000")
    montant_ttc_mga = Decimal("5000")


class AnFactEncaissementFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AnFactEncaissement

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    source_payment_id = factory.LazyFunction(uuid.uuid4)
    dim_temps = factory.SubFactory(AnDimTempsFactory, tenant=factory.SelfAttribute("..tenant"))
    reference = "PAY-0001"
    direction = "inbound"
    method = "especes"
    montant_mga = Decimal("10000")
    state = "posted"


class AnFactEcritureFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AnFactEcriture

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    source_line_id = factory.LazyFunction(uuid.uuid4)
    dim_temps = factory.SubFactory(AnDimTempsFactory, tenant=factory.SelfAttribute("..tenant"))
    compte_code = "701000"
    compte_libelle = "Ventes"
    compte_classe_pcg = 7
    debit_mga = Decimal("0")
    credit_mga = Decimal("10000")
    solde_mga = Decimal("-10000")


class AnWarehouseStateFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AnWarehouseState

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")


class AnRefreshRunFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AnRefreshRun

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    started_at = factory.LazyFunction(timezone.now)
    status = AnRefreshRun.STATUS_SUCCESS
    triggered_by = AnRefreshRun.TRIGGER_CRON


class AnMetricDefinitionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AnMetricDefinition

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"metric.{n}")
    libelle = factory.Sequence(lambda n: f"Indicateur {n}")
    module_source = "sales"
    statut = AnMetricDefinition.STATUT_PUBLIE
