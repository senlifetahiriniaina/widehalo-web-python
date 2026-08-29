"""PJ13 (`projects`, "Liaison KPI/Strategie") : `get_objective_summary`,
premier gap de LECTURE reellement consomme par un autre module — cf.
docstring de `apps/strategy/services/public.py`."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.strategy.models import StgObjective
from apps.strategy.services.objectives import add_key_result, create_objective
from apps.strategy.services.public import get_objective_summary

pytestmark = pytest.mark.django_db


def test_get_objective_summary_returns_title_status_and_key_results() -> None:
    tenant = Tenant.objects.create(code="STG-PUB1", name="Strategy Public Tenant")
    with use_tenant(tenant.id):
        objective = create_objective(
            tenant,
            title="Croissance CA 2026",
            level=StgObjective.LEVEL_COMPANY,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )
        add_key_result(
            objective,
            metric_name="CA MGA",
            target_value=Decimal("1000000"),
            current_value=Decimal("250000"),
            unit="MGA",
        )

        summary = get_objective_summary(tenant, objective.id)

    assert summary is not None
    assert summary["id"] == str(objective.id)
    assert summary["title"] == "Croissance CA 2026"
    assert summary["status"] == objective.status
    assert len(summary["key_results"]) == 1
    key_result = summary["key_results"][0]
    assert key_result["metric_name"] == "CA MGA"
    assert key_result["target_value"] == Decimal("1000000")
    assert key_result["current_value"] == Decimal("250000")
    assert key_result["progress_pct"] == Decimal("25.0000")


def test_get_objective_summary_returns_none_for_unknown_objective() -> None:
    tenant = Tenant.objects.create(code="STG-PUB2", name="Strategy Public Tenant 2")
    with use_tenant(tenant.id):
        summary = get_objective_summary(tenant, uuid.uuid4())

    assert summary is None


def test_get_objective_summary_returns_none_for_foreign_tenant_objective() -> None:
    tenant_a = Tenant.objects.create(code="STG-PUB3A", name="Strategy Tenant A")
    tenant_b = Tenant.objects.create(code="STG-PUB3B", name="Strategy Tenant B")
    with use_tenant(tenant_a.id):
        objective = create_objective(
            tenant_a,
            title="Objectif tenant A",
            level=StgObjective.LEVEL_COMPANY,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )
        objective_id = objective.id

    with use_tenant(tenant_b.id):
        summary = get_objective_summary(tenant_b, objective_id)

    assert summary is None


def test_get_objective_summary_returns_none_for_archived_objective() -> None:
    tenant = Tenant.objects.create(code="STG-PUB4", name="Strategy Public Tenant 4")
    with use_tenant(tenant.id):
        objective = create_objective(
            tenant,
            title="Objectif archive",
            level=StgObjective.LEVEL_COMPANY,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )
        objective.soft_delete()

        summary = get_objective_summary(tenant, objective.id)

    assert summary is None
