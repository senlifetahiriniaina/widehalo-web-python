"""REP6 : ecrans HTMX/session `reporting` (catalogue, generation, statut
de job, planifications)."""

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


def _login_client(user: User, password: str, tenant: Tenant) -> Client:
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def _grant(user: User, *, app_label: str, codenames: list[str]) -> None:
    group, _ = Group.objects.get_or_create(name=f"reporting-view-test-{'-'.join(codenames)}")
    group.permissions.add(
        *Permission.objects.filter(content_type__app_label=app_label, codename__in=codenames)
    )
    user.groups.add(group)


@pytest.fixture
def setup():
    tenant = Tenant.objects.create(code="RPT-VIEWS", name="Reporting Views Tenant")
    user = User.objects.create_user(email="rpt-views@example.com", password="Str0ngPassw0rd!23")
    _grant(
        user,
        app_label="reporting",
        codenames=[
            "view_rptdefinition",
            "add_rptjob",
            "view_rptjob",
            "view_rptschedule",
            "add_rptschedule",
            "change_rptschedule",
        ],
    )
    register_report(
        code="RPT-TEST-VIEW",
        module="reporting",
        label="Rapport de test ecran",
        permission="reporting.view_rptdefinition",
        render_rows=_rows,
        fields=("a",),
    )
    return tenant, user


def test_catalog_index_lists_accessible_reports(setup) -> None:
    tenant, user = setup
    client = _login_client(user, "Str0ngPassw0rd!23", tenant)
    response = client.get("/reporting/")
    assert response.status_code == 200
    assert b"RPT-TEST-VIEW" in response.content


def test_generate_form_denies_without_report_permission(setup) -> None:
    tenant, user = setup
    register_report(
        code="RPT-TEST-VIEW-DENY",
        module="accounting",
        label="Non autorise",
        permission="accounting.view_accaccount",
        render_rows=_rows,
    )
    client = _login_client(user, "Str0ngPassw0rd!23", tenant)
    response = client.get("/reporting/generate/RPT-TEST-VIEW-DENY/")
    assert response.status_code == 404


def test_generate_submit_creates_job_and_renders_status(setup) -> None:
    tenant, user = setup
    client = _login_client(user, "Str0ngPassw0rd!23", tenant)
    response = client.post(
        "/reporting/generate/RPT-TEST-VIEW/submit/", {"params": "{}", "format": "json"}
    )
    assert response.status_code == 200
    assert b"done" in response.content.lower() or "Termin" in response.content.decode("utf-8")


def test_schedules_index_get_and_post(setup) -> None:
    tenant, user = setup
    client = _login_client(user, "Str0ngPassw0rd!23", tenant)

    create_response = client.post(
        "/reporting/schedules/",
        {"code": "RPT-TEST-VIEW", "name": "Hebdo ecran", "frequency": "weekly", "format": "json"},
    )
    assert create_response.status_code == 200
    assert b"Hebdo ecran" in create_response.content

    list_response = client.get("/reporting/schedules/")
    assert list_response.status_code == 200
    assert b"Hebdo ecran" in list_response.content


def test_schedule_toggle_flips_enabled_state(setup) -> None:
    tenant, user = setup
    client = _login_client(user, "Str0ngPassw0rd!23", tenant)
    client.post(
        "/reporting/schedules/",
        {"code": "RPT-TEST-VIEW", "name": "A suspendre", "frequency": "daily", "format": "json"},
    )

    from apps.core.tests.utils import use_tenant
    from apps.reporting.models import RptSchedule

    with use_tenant(tenant.id):
        schedule = RptSchedule.objects.get(name="A suspendre")
        assert schedule.enabled is True

    toggle_response = client.post(f"/reporting/schedules/{schedule.id}/toggle/")
    assert toggle_response.status_code == 200

    with use_tenant(tenant.id):
        schedule.refresh_from_db()
        assert schedule.enabled is False
