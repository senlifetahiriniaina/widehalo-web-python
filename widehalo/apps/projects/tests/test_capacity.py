"""Tests PJ7 (equipe projet + heatmap de capacite, `services/capacity.py`)
— cf. plan, section « Module `projects` », etape PJ7."""

from __future__ import annotations

import datetime as dt

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.projects.services.capacity import (
    add_team_member,
    compute_project_capacity_summary,
    compute_user_workload_heatmap,
    remove_team_member,
)
from apps.projects.services.projects import create_project
from apps.projects.services.tasks import create_task

pytestmark = pytest.mark.django_db


@pytest.fixture
def capacity_ctx():
    tenant = Tenant.objects.create(code="PRJ-CAP", name="Projects Capacity Tenant")
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet avec equipe")
        user = User.objects.create_user(
            email="team-member@example.com", password="Str0ngPassw0rd!23"
        )
        yield tenant, project, user


# --- add_team_member ---------------------------------------------------------------


def test_add_team_member_happy_path(capacity_ctx) -> None:
    tenant, project, user = capacity_ctx
    with use_tenant(tenant.id):
        member = add_team_member(project, user, role="developpeur", allocation_pct=60)
        assert member.project_id == project.id
        assert member.user_id == user.id
        assert member.allocation_pct == 60


def test_add_team_member_rejects_allocation_out_of_range(capacity_ctx) -> None:
    tenant, project, user = capacity_ctx
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        add_team_member(project, user, allocation_pct=150)


def test_add_team_member_rejects_duplicate_membership(capacity_ctx) -> None:
    tenant, project, user = capacity_ctx
    with use_tenant(tenant.id):
        add_team_member(project, user, allocation_pct=40)
        with pytest.raises(ValidationError):
            add_team_member(project, user, allocation_pct=10)


def test_add_team_member_rejects_overallocation_across_projects(capacity_ctx) -> None:
    """Garde-fou central de PJ7 : la somme des `allocation_pct` de TOUS les
    projets ACTIFS d'un utilisateur ne doit jamais depasser 100 — la garde
    est declarative (somme de pourcentages annonces), pas une verification
    de disponibilite reelle jour par jour (cf. docstring de module)."""
    tenant, project, user = capacity_ctx
    with use_tenant(tenant.id):
        other_project = create_project(tenant, name="Second projet")
        add_team_member(project, user, allocation_pct=70)
        with pytest.raises(ValidationError):
            add_team_member(other_project, user, allocation_pct=40)
        # L'allocation restante (100-70=30) est encore acceptable.
        member = add_team_member(other_project, user, allocation_pct=30)
        assert member.allocation_pct == 30


def test_add_team_member_ignores_inactive_project_allocation(capacity_ctx) -> None:
    """Un projet desactive (soft-delete) ne compte plus dans la somme des
    allocations declarees — cf. `_total_allocation_pct` (`project__is_
    active=True`)."""
    tenant, project, user = capacity_ctx
    with use_tenant(tenant.id):
        other_project = create_project(tenant, name="Projet a desactiver")
        add_team_member(other_project, user, allocation_pct=90)
        other_project.soft_delete()
        # Le projet actif ci-dessus n'a plus a compter avec les 90% du
        # projet desactive.
        member = add_team_member(project, user, allocation_pct=50)
        assert member.allocation_pct == 50


def test_remove_team_member_is_a_soft_delete(capacity_ctx) -> None:
    tenant, project, user = capacity_ctx
    with use_tenant(tenant.id):
        member = add_team_member(project, user, allocation_pct=50)
        remove_team_member(member)
        member.refresh_from_db()
        assert member.is_active is False
        assert member.archived_at is not None
        # Retire (is_active=False) : une nouvelle affectation redevient
        # possible pour le meme couple projet/utilisateur.
        new_member = add_team_member(project, user, allocation_pct=20)
        assert new_member.is_active is True


# --- compute_project_capacity_summary -----------------------------------------------


def test_compute_project_capacity_summary(capacity_ctx) -> None:
    tenant, project, user = capacity_ctx
    with use_tenant(tenant.id):
        other_user = User.objects.create_user(
            email="team-member-2@example.com", password="Str0ngPassw0rd!23"
        )
        add_team_member(project, user, role="chef de projet", allocation_pct=40)
        add_team_member(project, other_user, role="developpeur", allocation_pct=80)

        summary = compute_project_capacity_summary(project)
        assert summary["project_id"] == str(project.id)
        assert summary["total_allocation_pct"] == 120
        assert len(summary["members"]) == 2


# --- compute_user_workload_heatmap ---------------------------------------------------


def test_compute_user_workload_heatmap_structure_and_values(capacity_ctx) -> None:
    """Cas verifie a la main : `user` alloue a 60% (un seul projet actif),
    2 taches actives assignees :
    - tache A : semaine 1 uniquement (jours 0-6) ;
    - tache B : semaines 1 ET 2 (jours 3-10), chevauche les deux.
    Semaine 3+ : aucune tache -> 0 tache active, meme allocation declaree
    (60%, constante sur tout l'horizon car c'est une donnee DECLAREE, pas
    calculee par semaine, cf. docstring de `compute_user_workload_heatmap`)."""
    tenant, project, user = capacity_ctx
    with use_tenant(tenant.id):
        add_team_member(project, user, allocation_pct=60)
        today = dt.date(2026, 1, 5)

        task_a = create_task(tenant, project=project, assignee=user)
        task_a.start_date = today
        task_a.end_date = today + dt.timedelta(days=2)
        task_a.save(update_fields=["start_date", "end_date"])

        task_b = create_task(tenant, project=project, assignee=user)
        task_b.start_date = today + dt.timedelta(days=3)
        task_b.end_date = today + dt.timedelta(days=10)
        task_b.save(update_fields=["start_date", "end_date"])

        heatmap = compute_user_workload_heatmap(user, horizon_weeks=4, today=today)

        assert len(heatmap) == 4
        week1, week2, week3, week4 = heatmap

        assert week1["week_start"] == today
        assert week1["week_end"] == today + dt.timedelta(days=6)
        assert week1["allocation_pct"] == 60
        assert week1["active_task_count"] == 2  # A (jours 0-2) et B (jours 3-6) chevauchent.
        assert week1["is_overallocated"] is False

        assert week2["week_start"] == today + dt.timedelta(days=7)
        assert week2["active_task_count"] == 1  # seule B (jours 3-10) chevauche jours 7-10.

        assert week3["active_task_count"] == 0
        assert week4["active_task_count"] == 0
        # Allocation declaree constante sur tout l'horizon.
        assert all(week["allocation_pct"] == 60 for week in heatmap)


def test_compute_user_workload_heatmap_ignores_task_without_dates(capacity_ctx) -> None:
    tenant, project, user = capacity_ctx
    with use_tenant(tenant.id):
        create_task(tenant, project=project, assignee=user)  # aucune date
        heatmap = compute_user_workload_heatmap(user, horizon_weeks=2)
        assert all(week["active_task_count"] == 0 for week in heatmap)


def test_compute_user_workload_heatmap_ignores_done_task(capacity_ctx) -> None:
    """Une tache `done` ne compte pas comme travail activement engage —
    meme discipline que `services/conflicts.py::_is_schedulable`."""
    tenant, project, user = capacity_ctx
    with use_tenant(tenant.id):
        from apps.projects.services.tasks import finish_task, start_task

        today = dt.date.today()
        task = create_task(tenant, project=project, assignee=user)
        task.start_date = today
        task.end_date = today + dt.timedelta(days=1)
        task.save(update_fields=["start_date", "end_date"])
        start_task(task, user)
        finish_task(task, user)

        heatmap = compute_user_workload_heatmap(user, horizon_weeks=1, today=today)
        assert heatmap[0]["active_task_count"] == 0


def test_compute_user_workload_heatmap_detects_declared_overallocation(capacity_ctx) -> None:
    """`is_overallocated` est recalcule a chaque lecture (pas seulement au
    moment de l'ajout) : simule une derive post-creation en modifiant
    directement `allocation_pct` d'une ligne existante (cf. disclosure de
    `PrjTeamMember` : rien n'empeche une edition ulterieure hors garde)."""
    tenant, project, user = capacity_ctx
    with use_tenant(tenant.id):
        member = add_team_member(project, user, allocation_pct=60)
        member.allocation_pct = 130
        member.save(update_fields=["allocation_pct"])

        heatmap = compute_user_workload_heatmap(user, horizon_weeks=1)
        assert heatmap[0]["allocation_pct"] == 130
        assert heatmap[0]["is_overallocated"] is True
