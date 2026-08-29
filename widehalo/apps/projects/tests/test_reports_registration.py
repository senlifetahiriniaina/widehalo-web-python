"""§5.11 reporting, PJ15 : verifie que les 3 rapports `projects` sont
enregistres dans le catalogue et exercables de bout en bout via le moteur
generique (`GET /reporting/catalog` + `POST /reporting/generate`), meme
patron que `apps.accounting.tests.test_reports_registration`."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.reports_registry import get_registered_report
from apps.core.tests.utils import grant_role, use_tenant
from apps.projects.services.evm import add_budget_line
from apps.projects.services.projects import create_project
from apps.projects.services.tasks import create_task

pytestmark = pytest.mark.django_db


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
def project_with_data():
    tenant = Tenant.objects.create(code="PRJ-RPT-REG", name="Projects Reporting Reg Tenant")
    user = User.objects.create_user(
        email="projects-rpt-reg@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(user, "resp_commercial")
    with use_tenant(tenant.id):
        project = create_project(
            tenant,
            name="Projet reporting",
            start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 12, 31),
        )
        task = create_task(
            tenant,
            project=project,
            start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 2, 1),
            duration_days=31,
        )
        task.percent_complete = 50
        task.save(update_fields=["percent_complete"])
        add_budget_line(
            project,
            category="opex",
            label="Ligne test",
            planned_amount=Decimal("1000.0000"),
            period=dt.date(2026, 1, 1),
            actual_amount=Decimal("500.0000"),
        )
    return tenant, user, project


def test_prj_reports_are_registered() -> None:
    for code in ("PRJ-GANTT", "PRJ-EVM", "PRJ-STATUS"):
        report = get_registered_report(code)
        assert report is not None, code
        assert report.module == "projects"


def test_prj_gantt_and_evm_support_rows_prj_status_supports_pdf() -> None:
    gantt = get_registered_report("PRJ-GANTT")
    evm = get_registered_report("PRJ-EVM")
    status = get_registered_report("PRJ-STATUS")
    assert gantt is not None and gantt.supports_rows() and not gantt.supports_pdf()
    assert evm is not None and evm.supports_rows() and not evm.supports_pdf()
    assert status is not None and status.supports_pdf() and not status.supports_rows()


def test_prj_gantt_render_rows_direct(project_with_data) -> None:
    tenant, _user, project = project_with_data
    report = get_registered_report("PRJ-GANTT")
    assert report is not None and report.render_rows is not None
    with use_tenant(tenant.id):
        rows = report.render_rows({"project_id": str(project.id)}, None)
    assert len(rows) == 1
    assert rows[0]["percent_complete"] == 50


def test_prj_evm_render_rows_direct(project_with_data) -> None:
    tenant, _user, project = project_with_data
    report = get_registered_report("PRJ-EVM")
    assert report is not None and report.render_rows is not None
    with use_tenant(tenant.id):
        rows = report.render_rows({"project_id": str(project.id)}, None)
    assert len(rows) == 1
    assert rows[0]["bac"] == Decimal("1000.0000")
    assert rows[0]["ac"] == Decimal("500.0000")


def test_prj_status_render_pdf_direct(project_with_data) -> None:
    tenant, _user, project = project_with_data
    report = get_registered_report("PRJ-STATUS")
    assert report is not None and report.render_pdf is not None
    with use_tenant(tenant.id):
        pdf_bytes = report.render_pdf({"project_id": str(project.id)}, None)
    assert pdf_bytes.startswith(b"%PDF")


@pytest.mark.parametrize(
    ("code", "fmt"),
    [("PRJ-GANTT", "json"), ("PRJ-EVM", "csv"), ("PRJ-STATUS", "pdf")],
)
def test_prj_reports_generate_end_to_end_via_api(project_with_data, code, fmt) -> None:
    """Exerce le chemin complet catalogue -> generation pour chacun des 3
    rapports PJ15 : `GET /reporting/catalog` les liste, `POST /reporting/
    generate` produit un job `done` avec un fichier non vide."""
    tenant, user, project = project_with_data
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    catalog_response = client.get("/api/v1/reporting/catalog", **headers)
    assert catalog_response.status_code == 200, catalog_response.content
    codes = {r["code"] for r in catalog_response.json()["results"]}
    assert code in codes

    generate_response = client.post(
        "/api/v1/reporting/generate",
        {"code": code, "params": {"project_id": str(project.id)}, "format": fmt},
        content_type="application/json",
        **headers,
    )
    assert generate_response.status_code == 200, generate_response.content
    job = generate_response.json()
    assert job["state"] == "done", job
    assert job["download_url"] is not None

    download_response = client.get(job["download_url"], **headers)
    assert download_response.status_code == 200
    assert len(download_response.content) > 0
