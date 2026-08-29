from __future__ import annotations

import calendar
import datetime as dt

import pytest
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


def test_bill_time_and_material_via_api_returns_501_stub(api_projects) -> None:
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
        f"/api/v1/projects/{project_id}/bill/time-and-material",
        {"hourly_rate": "100"},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 501


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
