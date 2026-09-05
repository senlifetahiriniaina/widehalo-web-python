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
    AnFactMouvementStock,
    AnFactOrdreFabrication,
    AnFactPaie,
    AnFactReception,
    AnFactTicketPos,
    AnFactVente,
    AnMetricDefinition,
    AnRefreshRun,
    AnWarehouseState,
)

_MOIS_LIBELLES = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]  # fmt: skip
_JOURS_LIBELLES = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


class AnDimTempsFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AnDimTemps

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    # Sequence (pas une date fixe) : `AnDimTemps` porte une contrainte
    # d'unicite (tenant, date) — un test qui cree plusieurs faits pour le
    # meme tenant sans dim_temps explicite ne doit jamais entrer en
    # collision avec lui-meme (cf. `services/refresh.py::_ensure_dim_temps`
    # pour le calcul reel des champs derives, reproduit ici a l'identique).
    date = factory.Sequence(lambda n: dt.date(2026, 9, 1) + dt.timedelta(days=n))
    annee = factory.LazyAttribute(lambda o: o.date.year)
    trimestre = factory.LazyAttribute(lambda o: (o.date.month - 1) // 3 + 1)
    mois = factory.LazyAttribute(lambda o: o.date.month)
    mois_libelle = factory.LazyAttribute(lambda o: _MOIS_LIBELLES[o.date.month - 1])
    semaine_iso = factory.LazyAttribute(lambda o: o.date.isocalendar()[1])
    jour_du_mois = factory.LazyAttribute(lambda o: o.date.day)
    jour_semaine_iso = factory.LazyAttribute(lambda o: o.date.isocalendar()[2])
    jour_semaine_libelle = factory.LazyAttribute(
        lambda o: _JOURS_LIBELLES[o.date.isocalendar()[2] - 1]
    )
    est_weekend = factory.LazyAttribute(lambda o: o.date.isocalendar()[2] in (6, 7))
    exercice_fiscal = factory.LazyAttribute(lambda o: o.date.year)


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


class AnFactMouvementStockFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AnFactMouvementStock

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    source_move_id = factory.LazyFunction(uuid.uuid4)
    dim_temps = factory.SubFactory(AnDimTempsFactory, tenant=factory.SelfAttribute("..tenant"))
    move_reference = "OF-0001"
    move_type = "transfert_interne"
    qty = Decimal("1")
    unit_cost_mga = Decimal("1000")
    value_mga = Decimal("1000")


class AnFactReceptionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AnFactReception

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    source_receipt_line_id = factory.LazyFunction(uuid.uuid4)
    dim_temps = factory.SubFactory(AnDimTempsFactory, tenant=factory.SelfAttribute("..tenant"))
    order_reference = "PO-0001"
    qty_received = Decimal("1")
    unit_price_mga = Decimal("1000")


class AnFactOrdreFabricationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AnFactOrdreFabrication

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    source_order_id = factory.LazyFunction(uuid.uuid4)
    dim_temps = factory.SubFactory(AnDimTempsFactory, tenant=factory.SelfAttribute("..tenant"))
    order_reference = "OF-0001"
    qty_produced = Decimal("1")
    cout_reel_mga = Decimal("1000")
    cout_planifie_mga = Decimal("900")
    ecart_cout_mga = Decimal("100")


class AnFactPaieFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AnFactPaie

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    source_payslip_id = factory.LazyFunction(uuid.uuid4)
    dim_temps = factory.SubFactory(AnDimTempsFactory, tenant=factory.SelfAttribute("..tenant"))
    employee_id = factory.LazyFunction(uuid.uuid4)
    period_code = "2026-03"
    payslip_reference = "BULL-2026-0001"
    state = "approved"
    gross_mga = Decimal("1000000")
    taxable_base_mga = Decimal("900000")
    irsa_mga = Decimal("50000")
    social_employee_mga = Decimal("15000")
    social_employer_mga = Decimal("140000")


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
