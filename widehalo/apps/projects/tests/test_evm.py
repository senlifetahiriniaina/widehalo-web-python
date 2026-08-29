"""Tests du service EVM (PJ4) — cf. `apps/projects/services/evm.py`.

Le test `test_compute_evm_snapshot_matches_manual_calculation` verifie le
calcul EVM A LA MAIN (meme discipline que ACC-IMP/RG-LOG-6 deja appliquee
dans ce projet) : un scenario a 2 lignes budgetaires + 2 taches, calcul
manuel de PV/EV/AC/BAC/SPI/CPI/EAC documente dans le docstring du test,
verifie que le service renvoie EXACTEMENT ces valeurs."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant
from apps.projects.models import PrjProject
from apps.projects.services.evm import (
    add_budget_line,
    compute_evm_snapshot,
    compute_project_health,
    compute_s_curve,
    refresh_project_health,
)
from apps.projects.services.projects import create_project
from apps.projects.services.tasks import create_task
from apps.projects.tests.factories import PrjBudgetLineFactory

pytestmark = pytest.mark.django_db


def _create_task_with_progress(tenant, *, project, duration_days, percent_complete):
    """`create_task` ne prend pas `percent_complete` en parametre (champ mis
    a jour uniquement par les transitions FSM ou l'utilisateur, cf.
    `services/tasks.py`) — petit helper de test qui cree la tache puis fixe
    directement l'avancement reel souhaite pour le scenario EVM."""
    task = create_task(tenant, project=project, duration_days=duration_days)
    task.percent_complete = percent_complete
    task.save(update_fields=["percent_complete"])
    return task


def test_compute_evm_snapshot_matches_manual_calculation() -> None:
    """Calcul manuel de reference :

    Projet du 2026-01-01 au 2026-01-11 (10 jours calendaires), instantane
    pris le 2026-01-06 (5 jours ecoules sur 10) -> fraction ecoulee = 0.5.

    2 lignes budgetaires :
      - CAPEX : planned=1000, actual=600
      - OPEX  : planned=500,  actual=300
    => BAC = 1000 + 500 = 1500
    => AC  = 600 + 300  = 900

    2 taches actives, ponderees par duration_days :
      - Tache A : duration_days=10, percent_complete=50
      - Tache B : duration_days=10, percent_complete=100
    Avancement pondere = (10*50 + 10*100) / (10+10) = 1500/20 = 75 %
    => EV = BAC * 0.75 = 1500 * 0.75 = 1125

    PV = BAC * fraction ecoulee = 1500 * 0.5 = 750

    SPI = EV / PV = 1125 / 750 = 1.5
    CPI = EV / AC = 1125 / 900 = 1.25
    EAC = AC + (BAC - EV) / CPI = 900 + (1500 - 1125) / 1.25
        = 900 + 375 / 1.25 = 900 + 300 = 1200
    """
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        project = create_project(
            tenant,
            name="Projet EVM manuel",
            start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 1, 11),
        )
        add_budget_line(
            project,
            category="capex",
            label="Materiel",
            planned_amount=Decimal("1000"),
            actual_amount=Decimal("600"),
            period=dt.date(2026, 1, 5),
        )
        add_budget_line(
            project,
            category="opex",
            label="Prestations",
            planned_amount=Decimal("500"),
            actual_amount=Decimal("300"),
            period=dt.date(2026, 1, 5),
        )
        _create_task_with_progress(tenant, project=project, duration_days=10, percent_complete=50)
        _create_task_with_progress(tenant, project=project, duration_days=10, percent_complete=100)

        snapshot = compute_evm_snapshot(project, as_of=dt.date(2026, 1, 6))

    assert snapshot.bac == Decimal("1500.0000")
    assert snapshot.ac == Decimal("900.0000")
    assert snapshot.pv == Decimal("750.0000")
    assert snapshot.ev == Decimal("1125.0000")
    assert snapshot.spi == Decimal("1.5000")
    assert snapshot.cpi == Decimal("1.2500")
    assert snapshot.eac == Decimal("1200.0000")


def test_compute_evm_snapshot_pv_none_without_project_dates() -> None:
    """PV non calculable (donc SPI aussi) quand le projet n'a pas les deux
    dates de debut/fin renseignees — jamais une exception, jamais une date
    inventee."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet sans dates")
        add_budget_line(
            project,
            category="opex",
            label="Ligne",
            planned_amount=Decimal("100"),
            period=dt.date(2026, 1, 1),
        )
        _create_task_with_progress(tenant, project=project, duration_days=1, percent_complete=50)

        snapshot = compute_evm_snapshot(project)

    assert snapshot.pv is None
    assert snapshot.spi is None
    # EV reste calculable (independant des dates du projet).
    assert snapshot.ev is not None


def test_compute_evm_snapshot_cpi_and_eac_none_on_zero_actual_cost() -> None:
    """Division par zero : AC=0 (aucun cout reel constate) -> CPI et EAC
    renvoient `None`, jamais une `ZeroDivisionError` ni une valeur
    inventee."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        project = create_project(
            tenant,
            name="Projet sans cout reel",
            start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 1, 11),
        )
        add_budget_line(
            project,
            category="opex",
            label="Ligne",
            planned_amount=Decimal("100"),
            actual_amount=Decimal("0"),
            period=dt.date(2026, 1, 1),
        )
        _create_task_with_progress(tenant, project=project, duration_days=1, percent_complete=50)

        snapshot = compute_evm_snapshot(project, as_of=dt.date(2026, 1, 6))

    assert snapshot.ac == Decimal("0.0000")
    assert snapshot.cpi is None
    assert snapshot.eac is None
    # PV reste calculable (denominateur different) : SPI l'est donc aussi.
    assert snapshot.pv is not None
    assert snapshot.spi is not None


def test_compute_evm_snapshot_pv_zero_at_project_start_gives_none_spi() -> None:
    """Division par zero symetrique : `as_of == start_date` -> PV=0 ->
    SPI=`None`."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        project = create_project(
            tenant,
            name="Projet a J0",
            start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 1, 11),
        )
        add_budget_line(
            project,
            category="opex",
            label="Ligne",
            planned_amount=Decimal("100"),
            actual_amount=Decimal("50"),
            period=dt.date(2026, 1, 1),
        )
        _create_task_with_progress(tenant, project=project, duration_days=1, percent_complete=10)

        snapshot = compute_evm_snapshot(project, as_of=dt.date(2026, 1, 1))

    assert snapshot.pv == Decimal("0.0000")
    assert snapshot.spi is None


def test_compute_evm_snapshot_ev_none_without_active_tasks() -> None:
    """EV non calculable (moyenne indefinie) quand le projet n'a aucune
    tache active."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        project = create_project(
            tenant,
            name="Projet sans tache",
            start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 1, 11),
        )
        add_budget_line(
            project,
            category="opex",
            label="Ligne",
            planned_amount=Decimal("100"),
            period=dt.date(2026, 1, 1),
        )

        snapshot = compute_evm_snapshot(project, as_of=dt.date(2026, 1, 6))

    assert snapshot.ev is None
    assert snapshot.spi is None
    assert snapshot.cpi is None
    assert snapshot.eac is None


@pytest.mark.parametrize(
    ("spi", "cpi", "expected"),
    [
        (Decimal("1.0"), Decimal("1.0"), PrjProject.STATUS_ON_TRACK),
        (Decimal("0.95"), Decimal("0.95"), PrjProject.STATUS_ON_TRACK),
        (Decimal("0.90"), Decimal("1.0"), PrjProject.STATUS_AT_RISK),
        (Decimal("1.0"), Decimal("0.90"), PrjProject.STATUS_AT_RISK),
        (Decimal("0.80"), Decimal("1.0"), PrjProject.STATUS_OFF_TRACK),
        (Decimal("1.0"), Decimal("0.80"), PrjProject.STATUS_OFF_TRACK),
        (None, Decimal("1.0"), None),
        (Decimal("1.0"), None, None),
    ],
)
def test_compute_project_health_thresholds(spi, cpi, expected) -> None:
    """Politique de seuils V1 (disclosee dans `services/evm.py`) : on_track
    si SPI et CPI >= 0.95, off_track si l'un des deux < 0.85, at_risk sinon,
    `None` si l'un des deux n'est pas calculable."""
    assert compute_project_health(spi, cpi) == expected


def test_refresh_project_health_updates_project_status() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        project = create_project(
            tenant,
            name="Projet a rafraichir",
            start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 1, 11),
        )
        assert project.status == PrjProject.STATUS_ON_TRACK
        add_budget_line(
            project,
            category="opex",
            label="Ligne",
            planned_amount=Decimal("1000"),
            actual_amount=Decimal("2000"),
            period=dt.date(2026, 1, 1),
        )
        _create_task_with_progress(tenant, project=project, duration_days=1, percent_complete=10)

        refresh_project_health(project, as_of=dt.date(2026, 1, 6))

        project.refresh_from_db()
    # AC(2000) tres superieur a EV -> CPI tres bas -> off_track.
    assert project.status == PrjProject.STATUS_OFF_TRACK


def test_refresh_project_health_leaves_status_unchanged_when_not_computable() -> None:
    """Aucune tache active -> EV/SPI/CPI non calculables -> le statut du
    projet n'est PAS modifie (garde sa valeur courante)."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet non calculable")
        project.status = PrjProject.STATUS_AT_RISK
        project.save(update_fields=["status"])

        refresh_project_health(project)

        project.refresh_from_db()
    assert project.status == PrjProject.STATUS_AT_RISK


def test_compute_s_curve_structure_and_cumulative_values() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet courbe en S")
        add_budget_line(
            project,
            category="capex",
            label="Janvier CAPEX",
            planned_amount=Decimal("100"),
            actual_amount=Decimal("80"),
            period=dt.date(2026, 1, 15),
        )
        add_budget_line(
            project,
            category="opex",
            label="Janvier OPEX",
            planned_amount=Decimal("50"),
            actual_amount=Decimal("40"),
            period=dt.date(2026, 1, 20),
        )
        add_budget_line(
            project,
            category="capex",
            label="Fevrier CAPEX",
            planned_amount=Decimal("200"),
            actual_amount=Decimal("0"),
            period=dt.date(2026, 2, 1),
        )

        points = compute_s_curve(project)

    assert [p["period"] for p in points] == ["2026-01-01", "2026-02-01"]
    january = points[0]
    assert january["capex_planned_cumulative"] == Decimal("100.0000")
    assert january["capex_actual_cumulative"] == Decimal("80.0000")
    assert january["opex_planned_cumulative"] == Decimal("50.0000")
    assert january["opex_actual_cumulative"] == Decimal("40.0000")
    february = points[1]
    # Cumule : 100 (janvier) + 200 (fevrier) = 300.
    assert february["capex_planned_cumulative"] == Decimal("300.0000")
    assert february["capex_actual_cumulative"] == Decimal("80.0000")
    # OPEX inchange en fevrier (aucune nouvelle ligne) -> cumul stable.
    assert february["opex_planned_cumulative"] == Decimal("50.0000")


def test_compute_s_curve_empty_project_returns_empty_list() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet sans budget")
        result = compute_s_curve(project)
    assert result == []


def test_compute_s_curve_rejects_unsupported_granularity() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet granularite")
        with pytest.raises(ValidationError):
            compute_s_curve(project, granularity="weekly")


def test_add_budget_line_rejects_unknown_category() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet categorie invalide")
        with pytest.raises(ValidationError):
            add_budget_line(
                project,
                category="unknown",
                label="Ligne",
                planned_amount=Decimal("10"),
                period=dt.date(2026, 1, 1),
            )


def test_add_budget_line_rejects_negative_planned_amount() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet montant negatif")
        with pytest.raises(ValidationError):
            add_budget_line(
                project,
                category="opex",
                label="Ligne",
                planned_amount=Decimal("-10"),
                period=dt.date(2026, 1, 1),
            )


def test_prj_budget_line_factory_creates_valid_instance() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        line = PrjBudgetLineFactory(tenant=tenant)
    assert line.pk is not None
    assert line.planned_amount == Decimal("1000.0000")
