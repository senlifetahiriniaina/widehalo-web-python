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
