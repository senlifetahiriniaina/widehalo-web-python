"""AI5 : adaptateur `apps.strategy.services.ai_insight_registration` —
verifie que la source REELLE lit correctement le `workload_pct` DEJA
calcule par `services.capacity_review.build_capacity_outlook` (CAP1-2) sur
des donnees `mrp` reelles, sans jamais recalculer une nouvelle capacite."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.services.insight_source_registry import get_insight_source
from apps.core.tests.utils import use_tenant
from apps.mrp.tests.factories import (
    MrpOrderFactory,
    MrpRoutingFactory,
    MrpRoutingStepFactory,
    MrpWorkcenterFactory,
    MrpWorkshopFactory,
)
from apps.strategy.services.ai_insight_registration import _capacity_trend

pytestmark = pytest.mark.django_db


def _planned_at(days_from_today: int) -> dt.datetime:
    return timezone.make_aware(
        dt.datetime.combine(dt.date.today() + dt.timedelta(days=days_from_today), dt.time(8, 0))
    )


def test_source_is_registered_in_the_shared_registry() -> None:
    registered = get_insight_source("strategy.capacity_trend")
    assert registered is not None
    assert registered.module == "strategy"
    assert registered.function is _capacity_trend


def test_source_surfaces_a_declining_workload_trend() -> None:
    tenant = Tenant.objects.create(code="STRAT-AI5-1", name="Strategie AI5 Tenant 1")
    with use_tenant(tenant.id):
        workshop = MrpWorkshopFactory(tenant=tenant, capacity_hours_day=Decimal("8"))
        routing = MrpRoutingFactory(tenant=tenant)
        MrpRoutingStepFactory(
            tenant=tenant,
            routing=routing,
            duration_min=2000,
            workcenter=MrpWorkcenterFactory(tenant=tenant, workshop=workshop),
        )
        # Charge concentree sur la 1ere semaine uniquement (jour+2) — la
        # derniere semaine de l'horizon (par defaut 90 jours) reste a 0%.
        MrpOrderFactory(
            tenant=tenant,
            workshop=workshop,
            routing=routing,
            qty=Decimal("1"),
            date_planned_start=_planned_at(2),
        )

        candidates = _capacity_trend(str(tenant.id))

    assert len(candidates) == 1
    assert candidates[0].category == "production"
    assert candidates[0].source_modules == ["strategy"]
    assert "baisse" in candidates[0].title


def test_source_ignores_a_stable_workload() -> None:
    tenant = Tenant.objects.create(code="STRAT-AI5-2", name="Strategie AI5 Tenant 2")
    with use_tenant(tenant.id):
        # Aucun `MrpWorkshop` -> capacite nulle sur toutes les semaines,
        # aucun signal de tendance a remonter (cf. docstring de
        # `_capacity_trend`).
        candidates = _capacity_trend(str(tenant.id))

    assert candidates == []
