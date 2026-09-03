from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.analytics.models import AnMetricDefinition
from apps.analytics.services.dictionary import register_metric
from apps.analytics.tests.factories import AnFactVenteFactory
from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.strategy.models import StgObjective
from apps.strategy.services.objectives import (
    activate_objective,
    add_key_result,
    compute_cascade_contribution,
    create_objective,
    recompute_objective_status,
    record_check_in,
    refresh_key_result_from_dictionary,
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


def test_add_key_result_rejects_unpublished_or_unknown_metric_code() -> None:
    tenant = Tenant.objects.create(code="STG-T7", name="Strategy Tenant 7")
    with use_tenant(tenant.id):
        objective = create_objective(
            tenant,
            title="Objectif indicateur",
            level=StgObjective.LEVEL_COMPANY,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )
        with pytest.raises(ValidationError):
            add_key_result(
                objective,
                metric_name="CA MGA",
                target_value=Decimal("1000000"),
                metric_code="code-inexistant",
            )

        register_metric(
            tenant,
            code="sales.ca_ht",
            libelle="CA HT",
            module_source="sales",
            statut=AnMetricDefinition.STATUT_BROUILLON,
        )
        with pytest.raises(ValidationError):
            add_key_result(
                objective,
                metric_name="CA MGA",
                target_value=Decimal("1000000"),
                metric_code="sales.ca_ht",
            )


def test_add_key_result_accepts_published_metric_code() -> None:
    tenant = Tenant.objects.create(code="STG-T8", name="Strategy Tenant 8")
    with use_tenant(tenant.id):
        register_metric(
            tenant,
            code="sales.ca_ht",
            libelle="CA HT",
            module_source="sales",
            statut=AnMetricDefinition.STATUT_PUBLIE,
        )
        objective = create_objective(
            tenant,
            title="Objectif indicateur publie",
            level=StgObjective.LEVEL_COMPANY,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )
        key_result = add_key_result(
            objective,
            metric_name="CA MGA",
            target_value=Decimal("1000000"),
            metric_code="sales.ca_ht",
        )
        assert key_result.metric_code == "sales.ca_ht"


def test_activate_objective_requires_a_measurable_key_result() -> None:
    tenant = Tenant.objects.create(code="STG-T9", name="Strategy Tenant 9")
    with use_tenant(tenant.id):
        objective = create_objective(
            tenant,
            title="Objectif brouillon",
            level=StgObjective.LEVEL_COMPANY,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )
        with pytest.raises(ValidationError):
            activate_objective(objective)

        add_key_result(
            objective, metric_name="Sans indicateur gouverne", target_value=Decimal("100")
        )
        with pytest.raises(ValidationError):
            activate_objective(objective)


def test_activate_objective_succeeds_once_measurable_key_result_exists() -> None:
    """`activate_objective` est une porte de validation pure — elle ne
    force JAMAIS `status` (toujours calculé, cf. docstring `models.py`) :
    `recompute_objective_status` a déjà fait sortir l'objectif de
    `STATUS_DRAFT` dès l'ajout du résultat clé (0% de progression -> à
    risque), l'activation ne fait que confirmer que cette sortie de
    brouillon est légitime au sens STR-1."""
    tenant = Tenant.objects.create(code="STG-T10", name="Strategy Tenant 10")
    with use_tenant(tenant.id):
        register_metric(
            tenant,
            code="sales.ca_ht",
            libelle="CA HT",
            module_source="sales",
            statut=AnMetricDefinition.STATUT_PUBLIE,
        )
        objective = create_objective(
            tenant,
            title="Objectif activable",
            level=StgObjective.LEVEL_COMPANY,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )
        add_key_result(
            objective,
            metric_name="CA MGA",
            target_value=Decimal("1000000"),
            metric_code="sales.ca_ht",
        )
        assert objective.status == StgObjective.STATUS_AT_RISK

        activated = activate_objective(objective)
        assert activated.status == StgObjective.STATUS_AT_RISK


def test_compute_cascade_contribution_never_double_counts_descendants() -> None:
    """STR-2 : chaque niveau ne porte que sa PROPRE progression, jamais une
    moyenne de ses descendants (qui compterait deux fois la meme donnee)."""
    tenant = Tenant.objects.create(code="STG-T11", name="Strategy Tenant 11")
    with use_tenant(tenant.id):
        company = create_objective(
            tenant,
            title="Entreprise",
            level=StgObjective.LEVEL_COMPANY,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )
        department = create_objective(
            tenant,
            title="Departement",
            level=StgObjective.LEVEL_DEPARTMENT,
            parent=company,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )
        individual = create_objective(
            tenant,
            title="Individuel",
            level=StgObjective.LEVEL_INDIVIDUAL,
            parent=department,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )
        # L'entreprise n'a AUCUN key result propre (sa progression propre
        # doit rester 0, jamais heriter de celle de ses descendants).
        department_kr = add_key_result(
            department, metric_name="KR departement", target_value=Decimal("100")
        )
        record_check_in(department_kr, date=datetime.date(2026, 6, 1), value=Decimal("50"))
        individual_kr = add_key_result(
            individual, metric_name="KR individuel", target_value=Decimal("100")
        )
        record_check_in(individual_kr, date=datetime.date(2026, 6, 1), value=Decimal("100"))

        chain = compute_cascade_contribution(individual)

        assert [row["level"] for row in chain] == [
            StgObjective.LEVEL_COMPANY,
            StgObjective.LEVEL_DEPARTMENT,
            StgObjective.LEVEL_INDIVIDUAL,
        ]
        by_level = {row["level"]: row["own_progress_pct"] for row in chain}
        assert by_level[StgObjective.LEVEL_COMPANY] == Decimal(0)
        assert by_level[StgObjective.LEVEL_DEPARTMENT] == Decimal(50)
        assert by_level[StgObjective.LEVEL_INDIVIDUAL] == Decimal(100)


def test_refresh_key_result_from_dictionary_requires_metric_code() -> None:
    tenant = Tenant.objects.create(code="STG-T12", name="Strategy Tenant 12")
    with use_tenant(tenant.id):
        objective = create_objective(
            tenant,
            title="Objectif sans indicateur",
            level=StgObjective.LEVEL_COMPANY,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )
        key_result = add_key_result(objective, metric_name="KR manuel", target_value=Decimal("100"))
        user = UserFactory()
        with pytest.raises(ValidationError):
            refresh_key_result_from_dictionary(tenant, key_result, user=user)


def test_refresh_key_result_from_dictionary_pulls_governed_value() -> None:
    """STR-1 : « l'avancement se calcule depuis l'indicateur, jamais saisi
    a la main » — passe par `bi.services.public.get_metric_current_value`,
    la meme fonction que le module BI."""
    tenant = Tenant.objects.create(code="STG-T13", name="Strategy Tenant 13")
    with use_tenant(tenant.id):
        register_metric(
            tenant,
            code="sales.ca_ht",
            libelle="CA HT",
            module_source="sales",
            statut=AnMetricDefinition.STATUT_PUBLIE,
        )
        AnFactVenteFactory(tenant=tenant, montant_ht_mga=Decimal("750"))
        objective = create_objective(
            tenant,
            title="Objectif gouverne",
            level=StgObjective.LEVEL_COMPANY,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )
        key_result = add_key_result(
            objective,
            metric_name="CA MGA",
            target_value=Decimal("1000"),
            metric_code="sales.ca_ht",
        )
        user = UserFactory()

        refreshed = refresh_key_result_from_dictionary(tenant, key_result, user=user)

        assert refreshed.current_value == Decimal("750")
