"""Ecrans HTMX §5.9.5 — verification de rendu (session-authentifie, pas
l'API JWT), meme discipline que `apps.logistics.tests.test_views` (non
exhaustif, verifie surtout l'absence d'erreur de template/queryset)."""

from __future__ import annotations

import datetime as dt

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.presence.services.absences import create_absence_type
from apps.presence.services.employees import create_employee

pytestmark = pytest.mark.django_db


@pytest.fixture
def web_presence():
    tenant = Tenant.objects.create(code="PRS-WEB", name="Presence Web Tenant")
    user = User.objects.create_user(email="rh-web@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "collaborateur")
    with use_tenant(tenant.id):
        employee = create_employee(
            tenant, first_name="Rina", last_name="Rakoto", hire_date=dt.date(2026, 1, 1), user=user
        )
        create_absence_type(tenant, code="CP-WEB", name="Congé payé", category="conge_paye")

    client = Client()
    client.force_login(user)
    return client, tenant, employee


def _with_tenant_session(client: Client, tenant: Tenant) -> None:
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()


def test_kiosk_screen_renders(web_presence) -> None:
    client, tenant, _employee = web_presence
    _with_tenant_session(client, tenant)
    response = client.get("/presence/kiosk/")
    assert response.status_code == 200


def test_team_calendar_screen_renders(web_presence) -> None:
    client, tenant, _employee = web_presence
    _with_tenant_session(client, tenant)
    response = client.get("/presence/team-calendar/")
    assert response.status_code == 200


def test_absence_request_screen_renders(web_presence) -> None:
    client, tenant, _employee = web_presence
    _with_tenant_session(client, tenant)
    response = client.get("/presence/absence-request/")
    assert response.status_code == 200


def test_dashboard_screen_renders(web_presence) -> None:
    client, tenant, _employee = web_presence
    _with_tenant_session(client, tenant)
    response = client.get("/presence/")
    assert response.status_code == 200


def test_reports_index_renders(web_presence) -> None:
    client, tenant, _employee = web_presence
    _with_tenant_session(client, tenant)
    response = client.get("/presence/reports/")
    assert response.status_code == 200
