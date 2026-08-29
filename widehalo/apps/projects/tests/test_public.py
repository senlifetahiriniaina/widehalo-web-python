"""PJ13 (« Liaison KPI/Strategie ») : `link_project_to_objective`/
`get_linked_objective_summary` — cf. docstring de `services/public.py`."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.projects.services.public import get_linked_objective_summary, link_project_to_objective
from apps.projects.tests.factories import PrjProjectFactory
from apps.strategy.models import StgObjective
from apps.strategy.services.objectives import add_key_result, create_objective

pytestmark = pytest.mark.django_db


def test_get_linked_objective_summary_returns_none_when_unset() -> None:
    tenant = Tenant.objects.create(code="PRJ-KPI1", name="Projects KPI Tenant 1")
    with use_tenant(tenant.id):
        project = PrjProjectFactory(tenant=tenant)

        assert get_linked_objective_summary(project) is None


def test_link_project_to_objective_then_read_summary() -> None:
    tenant = Tenant.objects.create(code="PRJ-KPI2", name="Projects KPI Tenant 2")
    with use_tenant(tenant.id):
        project = PrjProjectFactory(tenant=tenant)
        objective = create_objective(
            tenant,
            title="Croissance CA 2026",
            level=StgObjective.LEVEL_COMPANY,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )
        add_key_result(objective, metric_name="CA MGA", target_value=Decimal("100"), unit="MGA")

        link_project_to_objective(project, objective.id)
        project.refresh_from_db()

        assert project.linked_objective_id == objective.id

        summary = get_linked_objective_summary(project)

    assert summary is not None
    assert summary["title"] == "Croissance CA 2026"
    assert len(summary["key_results"]) == 1


def test_get_linked_objective_summary_returns_none_for_stale_reference() -> None:
    """Reference perimee/etrangere : `linked_objective_id` renseigne mais
    aucun `StgObjective` correspondant — jamais une exception, cf.
    docstring de `get_linked_objective_summary`."""
    tenant = Tenant.objects.create(code="PRJ-KPI3", name="Projects KPI Tenant 3")
    with use_tenant(tenant.id):
        project = PrjProjectFactory(tenant=tenant)
        link_project_to_objective(project, uuid.uuid4())

        assert get_linked_objective_summary(project) is None


def test_link_project_to_objective_can_unset() -> None:
    tenant = Tenant.objects.create(code="PRJ-KPI4", name="Projects KPI Tenant 4")
    with use_tenant(tenant.id):
        project = PrjProjectFactory(tenant=tenant)
        objective = create_objective(
            tenant,
            title="Objectif a delier",
            level=StgObjective.LEVEL_COMPANY,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )
        link_project_to_objective(project, objective.id)
        project.refresh_from_db()
        assert project.linked_objective_id is not None

        link_project_to_objective(project, None)
        project.refresh_from_db()

        assert project.linked_objective_id is None
