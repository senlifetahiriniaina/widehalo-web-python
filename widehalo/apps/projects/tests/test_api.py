from __future__ import annotations

import calendar
import datetime as dt
import io
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission
from django.test import Client

from apps.accounting.models import AccAccount, AccJournal
from apps.accounting.tests.factories import AccAccountFactory, AccJournalFactory, AccPeriodFactory
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.partners.tests.factories import PartnerFactory

pytestmark = pytest.mark.django_db


def _setup_accounting(tenant: Tenant) -> None:
    """Cf. `apps.projects.tests.test_billing._setup_accounting`."""
    AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_SALE)
    today = dt.date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    AccPeriodFactory(
        tenant=tenant, date_start=today.replace(day=1), date_end=today.replace(day=last_day)
    )
    AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_RECEIVABLE)
    AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_INCOME)


def _access_token(client: Client, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        {"email": email, "password": password},
        content_type="application/json",
    )
    return response.json()["access"]


def _headers(token: str, tenant_id: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": tenant_id}


@pytest.fixture
def api_projects():
    # `resp_commercial` porte la gestion de projet (cf. plan RBAC) et
    # n'est PAS dans `CORE_MFA_REQUIRED_ROLES` — pas de contournement JWT
    # necessaire, contrairement a `financing` (`admin`/`direction`/
    # `comptable`), cf. commentaire de `apps.financing.tests.test_api`.
    tenant = Tenant.objects.create(code="PRJ-API", name="Projects API Tenant")
    user = User.objects.create_user(email="projects-api@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "resp_commercial")
    return tenant, user


def test_create_and_read_project_via_api(api_projects) -> None:
    tenant, user = api_projects
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")

    response = client.post(
        "/api/v1/projects",
        {"name": "Projet API"},
        content_type="application/json",
        **_headers(token, str(tenant.id)),
    )
    assert response.status_code == 200, response.content
    project_id = response.json()["id"]

    response = client.get(f"/api/v1/projects/{project_id}", **_headers(token, str(tenant.id)))
    assert response.status_code == 200
    assert response.json()["name"] == "Projet API"
    assert response.json()["tasks"] == []


def test_create_task_and_transition_via_api(api_projects) -> None:
    tenant, user = api_projects
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")

    response = client.post(
        "/api/v1/projects",
        {"name": "Projet avec tache API"},
        content_type="application/json",
        **_headers(token, str(tenant.id)),
    )
    project_id = response.json()["id"]

    response = client.post(
        f"/api/v1/projects/{project_id}/tasks",
        {"task_type": "task"},
        content_type="application/json",
        **_headers(token, str(tenant.id)),
    )
    assert response.status_code == 200, response.content
    task_id = response.json()["id"]
    assert response.json()["state"] == "todo"

    response = client.post(
        f"/api/v1/projects/tasks/{task_id}/transition/start",
        content_type="application/json",
        **_headers(token, str(tenant.id)),
    )
    assert response.status_code == 200, response.content
    assert response.json()["state"] == "in_progress"


def test_unauthenticated_request_is_rejected() -> None:
    client = Client()
    response = client.get("/api/v1/projects")
    assert response.status_code == 401


def test_patch_task_gantt_updates_dates_and_recomputes_critical_path(api_projects) -> None:
    """PJ2 : l'endpoint drag-and-drop met a jour les dates de la tache et
    recalcule automatiquement le chemin critique du projet."""
    tenant, user = api_projects
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/projects", {"name": "Projet Gantt API"}, content_type="application/json", **headers
    )
    project_id = response.json()["id"]

    response = client.post(
        f"/api/v1/projects/{project_id}/tasks",
        {"duration_days": 5},
        content_type="application/json",
        **headers,
    )
    task_id = response.json()["id"]

    response = client.patch(
        f"/api/v1/projects/tasks/{task_id}/gantt",
        {"start_date": "2026-02-01", "end_date": "2026-02-10", "duration_days": 9},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["start_date"] == "2026-02-01"
    assert body["end_date"] == "2026-02-10"
    assert body["duration_days"] == 9
    # Une seule tache sans dependance -> chemin critique par definition.
    assert body["is_critical_path"] is True


def test_budget_endpoint_returns_lines_and_evm_snapshot(api_projects) -> None:
    """PJ4 : `GET .../budget` renvoie les lignes budgetaires creees via
    `POST .../budget` + un instantane EVM (SPI/CPI/EAC)."""
    tenant, user = api_projects
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/projects",
        {"name": "Projet budget API", "start_date": "2026-01-01", "end_date": "2026-01-11"},
        content_type="application/json",
        **headers,
    )
    project_id = response.json()["id"]

    response = client.post(
        f"/api/v1/projects/{project_id}/budget",
        {
            "category": "capex",
            "label": "Materiel",
            "planned_amount": "1000",
            "actual_amount": "500",
            "period": "2026-01-05",
        },
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200, response.content
    assert response.json()["planned_amount"] == "1000"

    response = client.get(f"/api/v1/projects/{project_id}/budget", **headers)
    assert response.status_code == 200, response.content
    body = response.json()
    assert len(body["lines"]) == 1
    assert body["lines"][0]["category"] == "capex"
    assert body["evm"]["bac"] == "1000.0000"
    assert body["evm"]["ac"] == "500.0000"


def test_create_budget_line_rejects_unknown_category(api_projects) -> None:
    tenant, user = api_projects
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/projects",
        {"name": "Projet categorie API"},
        content_type="application/json",
        **headers,
    )
    project_id = response.json()["id"]

    response = client.post(
        f"/api/v1/projects/{project_id}/budget",
        {"category": "unknown", "label": "Ligne", "planned_amount": "10", "period": "2026-01-01"},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 400


def test_budget_endpoint_requires_projects_view_permission() -> None:
    """RBAC : un role sans acces au module `projects` recoit 403."""
    tenant = Tenant.objects.create(code="PRJ-API-BUDGET-RBAC", name="Projects Budget RBAC Tenant")
    user = User.objects.create_user(
        email="projects-budget-rbac@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(user, "magasinier")
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get("/api/v1/projects/00000000-0000-0000-0000-000000000000/budget", **headers)
    assert response.status_code == 403


def test_patch_task_gantt_requires_projects_change_permission() -> None:
    """RBAC : un role sans acces au module `projects` recoit 403 (jamais
    une mise a jour silencieuse des dates)."""
    tenant = Tenant.objects.create(code="PRJ-API-RBAC", name="Projects API RBAC Tenant")
    user = User.objects.create_user(
        email="projects-api-rbac@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(user, "magasinier")
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.patch(
        "/api/v1/projects/tasks/00000000-0000-0000-0000-000000000000/gantt",
        {"duration_days": 1},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 403


# --- PJ5 : facturation multi-modes -------------------------------------------------


def test_bill_fixed_via_api(api_projects) -> None:
    """`resp_commercial` recoit `projects.bill_prjproject` (cf.
    `apps.core.services.rbac_policy.CUSTOM_PERMISSIONS`)."""
    tenant, user = api_projects
    with use_tenant(tenant.id):
        _setup_accounting(tenant)
        partner = PartnerFactory(tenant=tenant)
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/projects",
        {"name": "Projet facturable API", "client_partner_id": str(partner.id)},
        content_type="application/json",
        **headers,
    )
    project_id = response.json()["id"]

    response = client.post(
        f"/api/v1/projects/{project_id}/bill/fixed",
        {"amount": "5000"},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200, response.content
    assert response.json()["amount"] == "5000.0000"
    assert response.json()["mode"] == "fixed"

    # Deuxieme facturation forfaitaire du meme projet : refusee.
    response = client.post(
        f"/api/v1/projects/{project_id}/bill/fixed",
        {"amount": "1000"},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 400


def test_bill_time_and_material_via_api(api_projects) -> None:
    """PJ8 : le stub honnete de PJ5 est desormais implemente — 200 avec une
    facture creee des lors que des heures facturables non facturees
    existent."""
    tenant, user = api_projects
    with use_tenant(tenant.id):
        _setup_accounting(tenant)
        partner = PartnerFactory(tenant=tenant)
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/projects",
        {"name": "Projet regie API", "client_partner_id": str(partner.id)},
        content_type="application/json",
        **headers,
    )
    project_id = response.json()["id"]

    response = client.post(
        f"/api/v1/projects/{project_id}/tasks",
        {"task_type": "task"},
        content_type="application/json",
        **headers,
    )
    task_id = response.json()["id"]

    response = client.post(
        f"/api/v1/projects/tasks/{task_id}/time/manual",
        {
            "started_at": "2026-01-01T08:00:00Z",
            "stopped_at": "2026-01-01T13:00:00Z",
            "billable": True,
        },
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200, response.content

    response = client.post(
        f"/api/v1/projects/{project_id}/bill/time-and-material",
        {"hourly_rate": "100"},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200, response.content
    assert response.json()["amount"] == "500.0000"
    assert response.json()["mode"] == "time_and_material"

    # Rien de nouveau a facturer : les heures viennent d'etre marquees
    # `billed=True`.
    response = client.post(
        f"/api/v1/projects/{project_id}/bill/time-and-material",
        {"hourly_rate": "100"},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 400


# --- PJ8 : suivi du temps -----------------------------------------------------------


def test_start_stop_manual_time_entry_and_report_via_api(api_projects) -> None:
    tenant, user = api_projects
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/projects",
        {"name": "Projet chrono API"},
        content_type="application/json",
        **headers,
    )
    project_id = response.json()["id"]
    response = client.post(
        f"/api/v1/projects/{project_id}/tasks",
        {"task_type": "task"},
        content_type="application/json",
        **headers,
    )
    task_id = response.json()["id"]

    response = client.post(
        f"/api/v1/projects/tasks/{task_id}/time/start", content_type="application/json", **headers
    )
    assert response.status_code == 200, response.content
    time_entry_id = response.json()["id"]
    assert response.json()["stopped_at"] is None

    response = client.post(
        f"/api/v1/projects/time-entries/{time_entry_id}/stop",
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200, response.content
    assert response.json()["stopped_at"] is not None

    # Un deuxieme arret du meme chrono est refuse (deja arrete).
    response = client.post(
        f"/api/v1/projects/time-entries/{time_entry_id}/stop",
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 400

    response = client.post(
        f"/api/v1/projects/tasks/{task_id}/time/manual",
        {"started_at": "2026-01-01T08:00:00Z", "stopped_at": "2026-01-01T09:30:00Z"},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200, response.content
    assert response.json()["duration_minutes"] == 90

    response = client.get(f"/api/v1/projects/{project_id}/time-report", **headers)
    assert response.status_code == 200, response.content
    results = response.json()["results"]
    assert len(results) == 1
    # 90 minutes (saisie manuelle) + 1 minute (chrono demarre/arrete quasi
    # instantanement, `duration_minutes` toujours >= 1, cf. `services/
    # time_tracking.py::_duration_minutes`).
    assert results[0]["total_minutes"] == 91


def test_collaborateur_can_start_own_timer_but_not_stop_others(api_projects) -> None:
    """RBAC N3 (PJ8) : un `collaborateur` recoit `projects.
    track_prjtimeentry` (peut suivre SON PROPRE temps) mais ne peut pas
    arreter le chrono d'un collegue."""
    tenant, manager = api_projects
    collaborateur = User.objects.create_user(
        email="projects-collab@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(collaborateur, "collaborateur")
    client_manager = Client()
    manager_token = _access_token(client_manager, manager.email, "Str0ngPassw0rd!23")
    manager_headers = _headers(manager_token, str(tenant.id))

    response = client_manager.post(
        "/api/v1/projects",
        {"name": "Projet equipe API"},
        content_type="application/json",
        **manager_headers,
    )
    project_id = response.json()["id"]
    response = client_manager.post(
        f"/api/v1/projects/{project_id}/tasks",
        {"task_type": "task"},
        content_type="application/json",
        **manager_headers,
    )
    task_id = response.json()["id"]

    client_collab = Client()
    collab_token = _access_token(client_collab, collaborateur.email, "Str0ngPassw0rd!23")
    collab_headers = _headers(collab_token, str(tenant.id))

    # Le collaborateur demarre SON PROPRE chrono sur cette tache.
    response = client_collab.post(
        f"/api/v1/projects/tasks/{task_id}/time/start",
        content_type="application/json",
        **collab_headers,
    )
    assert response.status_code == 200, response.content
    collab_entry_id = response.json()["id"]

    # Le manager tente d'arreter le chrono du collaborateur : refuse.
    response = client_manager.post(
        f"/api/v1/projects/time-entries/{collab_entry_id}/stop",
        content_type="application/json",
        **manager_headers,
    )
    assert response.status_code == 400


def test_bill_fixed_via_api_requires_bill_prjproject_permission() -> None:
    """RBAC : `resp_production` gere la production/les taches (`projects.
    change_prjproject`) mais n'a PAS `projects.bill_prjproject` — refuse."""
    tenant = Tenant.objects.create(code="PRJ-API-BILL-RBAC", name="Projects Billing RBAC Tenant")
    user = User.objects.create_user(
        email="projects-billing-rbac@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(user, "resp_production")
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000000/bill/fixed",
        {"amount": "100"},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 403


# --- PJ6 : sprints/backlog/burndown/velocite via l'API --------------------------------


def test_create_start_and_complete_sprint_via_api(api_projects) -> None:
    tenant, user = api_projects
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/projects",
        {"name": "Projet sprints API"},
        content_type="application/json",
        **headers,
    )
    project_id = response.json()["id"]

    response = client.post(
        f"/api/v1/projects/{project_id}/sprints",
        {"name": "Sprint API 1", "start_date": "2026-01-01", "end_date": "2026-01-14"},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200, response.content
    sprint_id = response.json()["id"]
    assert response.json()["status"] == "planned"

    response = client.post(f"/api/v1/projects/{project_id}/sprints/{sprint_id}/start", **headers)
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "active"

    # Un second sprint actif sur le meme projet est refuse.
    response = client.post(
        f"/api/v1/projects/{project_id}/sprints",
        {"name": "Sprint API 2", "start_date": "2026-01-15", "end_date": "2026-01-28"},
        content_type="application/json",
        **headers,
    )
    sprint_2_id = response.json()["id"]
    response = client.post(f"/api/v1/projects/{project_id}/sprints/{sprint_2_id}/start", **headers)
    assert response.status_code == 400

    response = client.post(f"/api/v1/projects/{project_id}/sprints/{sprint_id}/complete", **headers)
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "completed"

    response = client.get(f"/api/v1/projects/{project_id}/sprints", **headers)
    assert response.status_code == 200
    assert {s["id"] for s in response.json()["results"]} == {sprint_id, sprint_2_id}


def test_backlog_burndown_and_velocity_endpoints_via_api(api_projects) -> None:
    tenant, user = api_projects
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/projects",
        {"name": "Projet backlog API"},
        content_type="application/json",
        **headers,
    )
    project_id = response.json()["id"]

    response = client.post(
        f"/api/v1/projects/{project_id}/tasks",
        {"story_points": 3},
        content_type="application/json",
        **headers,
    )
    task_id = response.json()["id"]

    response = client.get(f"/api/v1/projects/{project_id}/backlog", **headers)
    assert response.status_code == 200
    assert [t["id"] for t in response.json()["results"]] == [task_id]

    response = client.post(
        f"/api/v1/projects/{project_id}/sprints",
        {"name": "Sprint burndown API", "start_date": "2026-03-01", "end_date": "2026-03-01"},
        content_type="application/json",
        **headers,
    )
    sprint_id = response.json()["id"]

    response = client.get(f"/api/v1/projects/{project_id}/sprints/{sprint_id}/burndown", **headers)
    assert response.status_code == 200
    # Sprint d'un seul jour sans tache rattachee : un seul point, 0 restant.
    assert response.json()["burndown"] == [{"date": "2026-03-01", "story_points_remaining": "0"}]

    response = client.get(f"/api/v1/projects/{project_id}/velocity", **headers)
    assert response.status_code == 200
    assert response.json()["velocity"] == "0"


# --- PJ7 : equipe projet, heatmap de capacite, champs personnalises via l'API ---------


def test_team_management_via_api(api_projects) -> None:
    tenant, user = api_projects
    with use_tenant(tenant.id):
        member_user = User.objects.create_user(
            email="team-api-member@example.com", password="Str0ngPassw0rd!23"
        )
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/projects",
        {"name": "Projet equipe API"},
        content_type="application/json",
        **headers,
    )
    project_id = response.json()["id"]

    response = client.post(
        f"/api/v1/projects/{project_id}/team",
        {"user_id": str(member_user.id), "role": "developpeur", "allocation_pct": 50},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200, response.content
    member_id = response.json()["id"]
    assert response.json()["allocation_pct"] == 50

    # Sur-allocation refusee (50 + 60 > 100).
    response = client.post(
        f"/api/v1/projects/{project_id}/team",
        {"user_id": str(member_user.id), "role": "developpeur", "allocation_pct": 60},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 400

    response = client.get(f"/api/v1/projects/{project_id}/team", **headers)
    assert response.status_code == 200
    assert response.json()["total_allocation_pct"] == 50

    response = client.post(f"/api/v1/projects/{project_id}/team/{member_id}/remove", **headers)
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    response = client.get(f"/api/v1/projects/{project_id}/team", **headers)
    assert response.json()["total_allocation_pct"] == 0


def test_user_capacity_heatmap_via_api(api_projects) -> None:
    tenant, user = api_projects
    with use_tenant(tenant.id):
        member_user = User.objects.create_user(
            email="heatmap-api-member@example.com", password="Str0ngPassw0rd!23"
        )
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/projects",
        {"name": "Projet heatmap API"},
        content_type="application/json",
        **headers,
    )
    project_id = response.json()["id"]
    client.post(
        f"/api/v1/projects/{project_id}/team",
        {"user_id": str(member_user.id), "allocation_pct": 30},
        content_type="application/json",
        **headers,
    )

    response = client.get(f"/api/v1/projects/users/{member_user.id}/capacity-heatmap", **headers)
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["user_id"] == str(member_user.id)
    assert len(body["weeks"]) == 12  # DEFAULT_HORIZON_WEEKS
    assert all(week["allocation_pct"] == 30 for week in body["weeks"])


def test_custom_field_definitions_crud_via_api_reserved_to_admin() -> None:
    """RBAC : `projects.manage_prjcustomfielddefinition` est restreinte a
    `admin`/`direction` — `resp_commercial` (co-porteur de la gestion de
    projet courante) est explicitement REFUSE, cf. `apps.core.services.
    rbac_policy.CUSTOM_PERMISSIONS_MANAGE_PRJ_CUSTOM_FIELD_ROLES`. **Groupe
    ad hoc plutot que `grant_role("admin")`** : `admin` est dans
    `CORE_MFA_REQUIRED_ROLES`, ce qui bloquerait la connexion JWT de ce
    test tant qu'un device TOTP n'est pas enrole (meme constat/meme
    contournement que `apps.financing.tests.test_api::api_financing`, cf.
    son commentaire) — un groupe portant directement le codename personnalise
    exerce reellement le meme controle sans ce blocage."""
    tenant = Tenant.objects.create(code="PRJ-API-CFD", name="Projects Custom Fields API Tenant")
    admin_user = User.objects.create_user(
        email="projects-cfd-admin@example.com", password="Str0ngPassw0rd!23"
    )
    group, _ = Group.objects.get_or_create(name="projects-cfd-manage-test")
    group.permissions.set(
        Permission.objects.filter(
            content_type__app_label="projects",
            codename="manage_prjcustomfielddefinition",
        )
    )
    admin_user.groups.add(group)
    commercial_user = User.objects.create_user(
        email="projects-cfd-commercial@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(commercial_user, "resp_commercial")

    client = Client()
    admin_token = _access_token(client, admin_user.email, "Str0ngPassw0rd!23")
    admin_headers = _headers(admin_token, str(tenant.id))
    commercial_token = _access_token(client, commercial_user.email, "Str0ngPassw0rd!23")
    commercial_headers = _headers(commercial_token, str(tenant.id))

    response = client.post(
        "/api/v1/projects/config/custom-fields",
        {
            "entity_type": "task",
            "field_key": "budget_code",
            "field_label": "Code budgetaire",
            "field_type": "text",
            "validation_rule": {"required": True},
        },
        content_type="application/json",
        **admin_headers,
    )
    assert response.status_code == 200, response.content
    definition_id = response.json()["id"]

    response = client.get("/api/v1/projects/config/custom-fields", **admin_headers)
    assert response.status_code == 200
    assert len(response.json()["results"]) == 1

    # `resp_commercial` refuse malgre son acces large au module `projects`.
    response = client.get("/api/v1/projects/config/custom-fields", **commercial_headers)
    assert response.status_code == 403
    response = client.post(
        "/api/v1/projects/config/custom-fields",
        {
            "entity_type": "task",
            "field_key": "autre_champ",
            "field_label": "Autre",
            "field_type": "text",
        },
        content_type="application/json",
        **commercial_headers,
    )
    assert response.status_code == 403

    response = client.post(
        f"/api/v1/projects/config/custom-fields/{definition_id}/remove", **admin_headers
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False


# --- PJ10 : wiki projet + rattachement de documents -------------------------


def test_wiki_page_crud_via_api(api_projects) -> None:
    tenant, user = api_projects
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/projects",
        {"name": "Projet wiki API"},
        content_type="application/json",
        **headers,
    )
    project_id = response.json()["id"]

    response = client.post(
        f"/api/v1/projects/{project_id}/wiki",
        {"title": "Page racine", "body": "Contenu"},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200, response.content
    page_id = response.json()["id"]
    assert response.json()["title"] == "Page racine"

    response = client.post(
        f"/api/v1/projects/{project_id}/wiki",
        {"title": "Page enfant", "parent_id": page_id},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200
    child_id = response.json()["id"]

    response = client.get(f"/api/v1/projects/{project_id}/wiki", **headers)
    assert response.status_code == 200
    assert [row["id"] for row in response.json()["results"]] == [page_id]

    response = client.get(f"/api/v1/projects/wiki/{child_id}", **headers)
    assert response.status_code == 200
    assert response.json()["parent_id"] == page_id

    response = client.patch(
        f"/api/v1/projects/wiki/{page_id}",
        {"title": "Page racine modifiee"},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Page racine modifiee"


def test_wiki_page_rejects_parent_from_another_project_via_api(api_projects) -> None:
    tenant, user = api_projects
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/projects", {"name": "Projet A"}, content_type="application/json", **headers
    )
    project_a_id = response.json()["id"]
    response = client.post(
        "/api/v1/projects", {"name": "Projet B"}, content_type="application/json", **headers
    )
    project_b_id = response.json()["id"]

    response = client.post(
        f"/api/v1/projects/{project_a_id}/wiki",
        {"title": "Page A"},
        content_type="application/json",
        **headers,
    )
    page_a_id = response.json()["id"]

    response = client.post(
        f"/api/v1/projects/{project_b_id}/wiki",
        {"title": "Page B avec parent errone", "parent_id": page_a_id},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 400


def test_attach_document_to_wiki_page_and_project_via_api(api_projects) -> None:
    tenant, user = api_projects
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/projects",
        {"name": "Projet documents API"},
        content_type="application/json",
        **headers,
    )
    project_id = response.json()["id"]
    response = client.post(
        f"/api/v1/projects/{project_id}/wiki",
        {"title": "Page avec doc"},
        content_type="application/json",
        **headers,
    )
    page_id = response.json()["id"]

    upload = io.BytesIO(b"contenu du document de wiki")
    upload.name = "wiki-doc.txt"
    response = client.post(
        f"/api/v1/projects/wiki/{page_id}/documents", {"file": upload}, **headers
    )
    assert response.status_code == 200, response.content
    assert response.json()["original_name"] == "wiki-doc.txt"

    upload2 = io.BytesIO(b"cahier des charges projet")
    upload2.name = "cahier.txt"
    response = client.post(f"/api/v1/projects/{project_id}/documents", {"file": upload2}, **headers)
    assert response.status_code == 200, response.content

    response = client.get(f"/api/v1/projects/{project_id}/documents", **headers)
    assert response.status_code == 200
    names = {row["original_name"] for row in response.json()["results"]}
    assert names == {"cahier.txt"}


def test_wiki_endpoints_require_projects_view_permission() -> None:
    """RBAC : un role sans acces au module `projects` recoit 403."""
    tenant = Tenant.objects.create(code="PRJ-API-WIKI-RBAC", name="Projects Wiki RBAC Tenant")
    user = User.objects.create_user(
        email="projects-wiki-rbac@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(user, "magasinier")
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get("/api/v1/projects/00000000-0000-0000-0000-000000000000/wiki", **headers)
    assert response.status_code == 403


def test_link_objective_endpoint_then_kpi_summary_includes_it(api_projects) -> None:
    """PJ13 : `PATCH .../link-objective` puis `GET .../kpi-summary` renvoie
    le resume de l'objectif (titre/statut/key results) a cote de l'EVM."""
    from apps.strategy.models import StgObjective
    from apps.strategy.services.objectives import add_key_result, create_objective

    tenant, user = api_projects
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/projects", {"name": "Projet KPI"}, content_type="application/json", **headers
    )
    project_id = response.json()["id"]

    with use_tenant(tenant.id):
        objective = create_objective(
            tenant,
            title="Objectif API",
            level=StgObjective.LEVEL_COMPANY,
            period_start=dt.date(2026, 1, 1),
            period_end=dt.date(2026, 12, 31),
        )
        add_key_result(objective, metric_name="CA MGA", target_value=Decimal("100"))

    response = client.patch(
        f"/api/v1/projects/{project_id}/link-objective",
        {"objective_id": str(objective.id)},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200, response.content
    assert response.json()["linked_objective_id"] == str(objective.id)

    response = client.get(f"/api/v1/projects/{project_id}/kpi-summary", **headers)
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["linked_objective"]["title"] == "Objectif API"
    assert body["linked_objective"]["key_results"][0]["metric_name"] == "CA MGA"
    assert "spi" in body["evm"]

    response = client.patch(
        f"/api/v1/projects/{project_id}/link-objective",
        {"objective_id": None},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200, response.content
    assert response.json()["linked_objective_id"] is None

    response = client.get(f"/api/v1/projects/{project_id}/kpi-summary", **headers)
    assert response.json()["linked_objective"] is None


def test_kpi_summary_endpoint_requires_view_permission() -> None:
    tenant = Tenant.objects.create(code="PRJ-API-KPI-RBAC", name="Projects KPI RBAC Tenant")
    user = User.objects.create_user(
        email="projects-kpi-rbac@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(user, "magasinier")
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get(
        "/api/v1/projects/00000000-0000-0000-0000-000000000000/kpi-summary", **headers
    )
    assert response.status_code == 403
