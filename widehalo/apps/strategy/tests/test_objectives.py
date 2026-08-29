from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.strategy.models import StgObjective
from apps.strategy.services.objectives import (
    add_key_result,
    create_objective,
    recompute_objective_status,
    record_check_in,
    refresh_key_result_from_source,
)

pytestmark = pytest.mark.django_db


def test_okr_cascade_company_department_individual() -> None:
    tenant = Tenant.objects.create(code="STG-T1", name="Strategy Tenant")
    with use_tenant(tenant.id):
        owner = UserFactory()
        company = create_objective(
            tenant,
            title="Croissance CA 2026",
            level=StgObjective.LEVEL_COMPANY,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
            owner=owner,
        )
        department = create_objective(
            tenant,
            title="CA commercial 2026",
            level=StgObjective.LEVEL_DEPARTMENT,
            parent=company,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )
        individual = create_objective(
            tenant,
            title="CA vendeur X 2026",
            level=StgObjective.LEVEL_INDIVIDUAL,
            parent=department,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )
        assert individual.parent_id == department.id
        assert department.parent_id == company.id
        assert individual.status == StgObjective.STATUS_DRAFT


def test_cascade_rejects_individual_as_parent_of_company() -> None:
    tenant = Tenant.objects.create(code="STG-T2", name="Strategy Tenant 2")
    with use_tenant(tenant.id):
        individual = create_objective(
            tenant,
            title="Objectif individuel",
            level=StgObjective.LEVEL_INDIVIDUAL,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )
        with pytest.raises(ValidationError):
            create_objective(
                tenant,
                title="Objectif entreprise invalide",
                level=StgObjective.LEVEL_COMPANY,
                parent=individual,
                period_start=datetime.date(2026, 1, 1),
                period_end=datetime.date(2026, 12, 31),
            )


def test_status_computed_from_key_result_progress_never_fsm() -> None:
    tenant = Tenant.objects.create(code="STG-T3", name="Strategy Tenant 3")
    with use_tenant(tenant.id):
        objective = create_objective(
            tenant,
            title="Objectif avec KR",
            level=StgObjective.LEVEL_COMPANY,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )
        assert objective.status == StgObjective.STATUS_DRAFT

        key_result = add_key_result(
            objective, metric_name="CA MGA", target_value=Decimal("1000000")
        )
        objective.refresh_from_db()
        # aucune progression -> a risque (0% < seuil on_track)
        assert objective.status == StgObjective.STATUS_AT_RISK

        record_check_in(key_result, date=datetime.date(2026, 6, 1), value=Decimal("800000"))
        objective.refresh_from_db()
        assert objective.status == StgObjective.STATUS_ON_TRACK

        record_check_in(key_result, date=datetime.date(2026, 7, 1), value=Decimal("1000000"))
        objective.refresh_from_db()
        assert objective.status == StgObjective.STATUS_ACHIEVED

        # jamais de champ/mecanisme FSM sur ce modele (simplification
        # deliberee, cf. plan/docstring models.py) — pas d'attribut
        # `get_available_state_transitions`/`_get_FIELD_display` de FSM.
        assert not hasattr(objective, "_field_transition_states")


def test_status_missed_when_period_ended_below_target() -> None:
    tenant = Tenant.objects.create(code="STG-T4", name="Strategy Tenant 4")
    with use_tenant(tenant.id):
        objective = create_objective(
            tenant,
            title="Objectif expire",
            level=StgObjective.LEVEL_COMPANY,
            period_start=datetime.date(2020, 1, 1),
            period_end=datetime.date(2020, 12, 31),
        )
        key_result = add_key_result(
            objective, metric_name="CA MGA", target_value=Decimal("1000000")
        )
        record_check_in(key_result, date=datetime.date(2020, 6, 1), value=Decimal("200000"))
        objective.refresh_from_db()
        assert objective.status == StgObjective.STATUS_MISSED


def test_refresh_key_result_from_unknown_source_raises_explicit_error() -> None:
    tenant = Tenant.objects.create(code="STG-T5", name="Strategy Tenant 5")
    with use_tenant(tenant.id):
        objective = create_objective(
            tenant,
            title="Objectif source KPI",
            level=StgObjective.LEVEL_COMPANY,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )
        key_result = add_key_result(
            objective,
            metric_name="CA MGA",
            target_value=Decimal("1000000"),
            kpi_source_module="sales",
            kpi_source_function="fonction_inexistante",
        )
        with pytest.raises(ValidationError):
            refresh_key_result_from_source(tenant, key_result)


def test_recompute_status_no_key_results_stays_draft() -> None:
    tenant = Tenant.objects.create(code="STG-T6", name="Strategy Tenant 6")
    with use_tenant(tenant.id):
        objective = create_objective(
            tenant,
            title="Objectif vide",
            level=StgObjective.LEVEL_COMPANY,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )
        assert recompute_objective_status(objective) == StgObjective.STATUS_DRAFT
