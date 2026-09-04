"""Factories factory_boy pour les modeles du module `strategy` — une par
modele concret (couche T1 du plan de durcissement, CDC §14 couches).

`tenant` est resolu via un `SubFactory` a chemin pointe vers
`apps.core.tests.factories.TenantFactory` (resolution paresseuse, meme
convention que tous les autres modules)."""

from __future__ import annotations

import datetime
from decimal import Decimal

import factory
from django.utils import timezone

from apps.strategy.models import (
    SECTOR_TEXTILE,
    StgBudget,
    StgCheckIn,
    StgInitiative,
    StgKeyResult,
    StgNote,
    StgObjective,
    StgReviewPack,
    StgRisk,
    StgSectorBenchmark,
)


class StgObjectiveFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StgObjective

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    title = factory.Sequence(lambda n: f"Objectif {n}")
    level = StgObjective.LEVEL_COMPANY
    period_start = datetime.date(2026, 1, 1)
    period_end = datetime.date(2026, 12, 31)


class StgKeyResultFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StgKeyResult

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    objective = factory.SubFactory(StgObjectiveFactory, tenant=factory.SelfAttribute("..tenant"))
    metric_name = factory.Sequence(lambda n: f"Indicateur {n}")
    target_value = Decimal("100")
    current_value = Decimal("0")
    unit = "unite"


class StgCheckInFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StgCheckIn

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    key_result = factory.SubFactory(StgKeyResultFactory, tenant=factory.SelfAttribute("..tenant"))
    date = datetime.date(2026, 6, 1)
    value = Decimal("50")


class StgSectorBenchmarkFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StgSectorBenchmark

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    sector_code = SECTOR_TEXTILE
    kpi_code = factory.Sequence(lambda n: f"KPI{n}")
    kpi_label = factory.Sequence(lambda n: f"Indicateur sectoriel {n}")
    valid_from = datetime.date(2026, 1, 1)


class StgNoteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StgNote

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    title = factory.Sequence(lambda n: f"Note {n}")
    body = "Contenu redige par la direction."


class StgBudgetFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StgBudget

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Budget {n}")
    period_start = datetime.date(2026, 1, 1)
    period_end = datetime.date(2026, 12, 31)
    lines = factory.LazyFunction(list)


class StgInitiativeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StgInitiative

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    objective = factory.SubFactory(StgObjectiveFactory, tenant=factory.SelfAttribute("..tenant"))
    title = factory.Sequence(lambda n: f"Initiative {n}")


class StgRiskFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StgRisk

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    title = factory.Sequence(lambda n: f"Risque {n}")
    probability = 3
    impact = 3


class StgReviewPackFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StgReviewPack

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    period_start = datetime.date(2026, 1, 1)
    period_end = datetime.date(2026, 3, 31)
    generated_at = factory.LazyFunction(timezone.now)
    snapshot = factory.LazyFunction(dict)
