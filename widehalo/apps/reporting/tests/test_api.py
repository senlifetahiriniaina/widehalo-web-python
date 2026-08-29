from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, Permission
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.reports_registry import register_report

pytestmark = pytest.mark.django_db


def _rows(params: dict, actor) -> list[dict]:  # noqa: ANN001
    return [{"a": 1}]


def _access_token(client: Client, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        {"email": email, "password": password},
        content_type="application/json",
    )
    return response.json()["access"]


def _headers(token: str, tenant_id: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": tenant_id}


def test_catalog_endpoint_filters_by_underlying_report_permission() -> None:
    """RPT-5/RPT-11 : le catalogue ne renvoie que les rapports dont
    l'utilisateur possede reellement la permission — `reporting.view_
    rptdefinition` (accordee a tous les roles) ouvre l'ACCES A L'ENDPOINT,
    pas la visibilite de chaque rapport pris individuellement."""
    register_report(
        code="RPT-TEST-VISIBLE-COMPTABLE",
        module="accounting",
        label="Visible comptable",
        permission="accounting.view_accaccount",
        render_rows=_rows,
    )
    register_report(
        code="RPT-TEST-VISIBLE-RH",
        module="payroll",
        label="Visible RH",
        permission="payroll.view_paypayslip",
        render_rows=_rows,
    )
    tenant = Tenant.objects.create(code="RPT-API", name="Reporting API Tenant")
    user = User.objects.create_user(email="rpt-api@example.com", password="Str0ngPassw0rd!23")
    # Pas `grant_role(user, "comptable")` : "comptable" fait partie de
    # CORE_MFA_REQUIRED_ROLES (Lot 1, etape 4) et bloquerait la connexion
    # JWT de ce test tant qu'un device TOTP n'est pas enrole (meme piege que
    # documente dans `apps.accounting.tests.test_api`) — groupe ad hoc avec
    # exactement les permissions exercees par ce test a la place.
    group, _ = Group.objects.get_or_create(name="reporting-api-test")
    group.permissions.add(
        *Permission.objects.filter(
            content_type__app_label="reporting", codename="view_rptdefinition"
        ),
        *Permission.objects.filter(
            content_type__app_label="accounting", codename="view_accaccount"
        ),
    )
    user.groups.add(group)

    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    response = client.get("/api/v1/reporting/catalog", **_headers(token, str(tenant.id)))

    assert response.status_code == 200
    codes = {row["code"] for row in response.json()["results"]}
    assert "RPT-TEST-VISIBLE-COMPTABLE" in codes
    assert "RPT-TEST-VISIBLE-RH" not in codes


def test_catalog_endpoint_requires_authentication() -> None:
    client = Client()
    response = client.get("/api/v1/reporting/catalog")
    assert response.status_code == 401


def _grant(user: User, *, app_label: str, codenames: list[str]) -> None:
    group, _ = Group.objects.get_or_create(name=f"reporting-api-test-{'-'.join(codenames)}")
    group.permissions.add(
        *Permission.objects.filter(content_type__app_label=app_label, codename__in=codenames)
    )
    user.groups.add(group)


def test_generate_endpoint_denies_when_missing_underlying_report_permission() -> None:
    register_report(
        code="RPT-TEST-API-GEN-DENY",
        module="accounting",
        label="Gen deny",
        permission="accounting.view_accaccount",
        render_rows=_rows,
    )
    tenant = Tenant.objects.create(code="RPT-API-DENY", name="Reporting API Deny Tenant")
    user = User.objects.create_user(email="rpt-api-deny@example.com", password="Str0ngPassw0rd!23")
    _grant(user, app_label="reporting", codenames=["add_rptjob", "view_rptjob"])

    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    response = client.post(
        "/api/v1/reporting/generate",
        {"code": "RPT-TEST-API-GEN-DENY", "format": "json"},
        content_type="application/json",
        **_headers(token, str(tenant.id)),
    )
    assert response.status_code == 403


def test_generate_status_and_download_round_trip() -> None:
    register_report(
        code="RPT-TEST-API-GEN-OK",
        module="reporting",
        label="Gen ok",
        permission="reporting.view_rptdefinition",
        render_rows=_rows,
        fields=("a",),
    )
    tenant = Tenant.objects.create(code="RPT-API-OK", name="Reporting API OK Tenant")
    user = User.objects.create_user(email="rpt-api-ok@example.com", password="Str0ngPassw0rd!23")
    _grant(
        user,
        app_label="reporting",
        codenames=["add_rptjob", "view_rptjob", "view_rptdefinition"],
    )

    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    generate_response = client.post(
        "/api/v1/reporting/generate",
        {"code": "RPT-TEST-API-GEN-OK", "format": "csv"},
        content_type="application/json",
        **headers,
    )
    assert generate_response.status_code == 200
    job_id = generate_response.json()["id"]
    assert generate_response.json()["state"] == "done"

    status_response = client.get(f"/api/v1/reporting/jobs/{job_id}", **headers)
    assert status_response.status_code == 200
    assert status_response.json()["state"] == "done"

    download_response = client.get(f"/api/v1/reporting/jobs/{job_id}/download", **headers)
    assert download_response.status_code == 200
    assert b"a" in download_response.content


def test_create_and_toggle_schedule_round_trip() -> None:
    register_report(
        code="RPT-TEST-API-SCHEDULE",
        module="reporting",
        label="Schedule API",
        permission="reporting.view_rptdefinition",
        render_rows=_rows,
        fields=("a",),
    )
    tenant = Tenant.objects.create(code="RPT-API-SCHED", name="Reporting API Schedule Tenant")
    user = User.objects.create_user(email="rpt-api-sched@example.com", password="Str0ngPassw0rd!23")
    _grant(
        user,
        app_label="reporting",
        codenames=[
            "add_rptschedule",
            "view_rptschedule",
            "change_rptschedule",
            "view_rptdefinition",
        ],
    )

    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/reporting/schedules",
        {
            "name": "Hebdo test API",
            "code": "RPT-TEST-API-SCHEDULE",
            "frequency": "weekly",
            "format": "json",
        },
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    schedule_id = create_response.json()["id"]
    assert create_response.json()["enabled"] is True

    list_response = client.get("/api/v1/reporting/schedules", **headers)
    assert list_response.status_code == 200
    assert any(row["id"] == schedule_id for row in list_response.json()["results"])

    toggle_response = client.post(f"/api/v1/reporting/schedules/{schedule_id}/toggle", **headers)
    assert toggle_response.status_code == 200
    assert toggle_response.json()["enabled"] is False
