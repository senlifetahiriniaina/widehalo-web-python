from __future__ import annotations

import datetime as dt

import pytest

from apps.core.tests.factories import TenantFactory, UserFactory
from apps.core.tests.utils import use_tenant
from apps.presence.models import PrsEmployeeSkill, PrsEmployeeTask
from apps.presence.services.documents_tracking import (
    add_employee_document,
    notify_document_alert,
    upcoming_document_alerts,
)
from apps.presence.services.employees import create_employee
from apps.presence.services.onboarding import (
    DEFAULT_ONBOARDING_STEPS,
    complete_onboarding_task,
    onboarding_progress,
    trigger_onboarding_checklist,
)
from apps.presence.services.org_chart import render_org_chart_svg
from apps.presence.services.skills import find_employees_with_skill, set_employee_skill_level

pytestmark = pytest.mark.django_db


def test_set_and_query_employee_skill() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        employee = create_employee(
            tenant, first_name="Rina", last_name="Rakoto", hire_date=dt.date(2026, 1, 1)
        )
        set_employee_skill_level(employee, skill_name="Piqure industrielle", level="expert")
        matches = find_employees_with_skill(
            tenant, skill_name="Piqure industrielle", min_level="confirme"
        )
        assert len(matches) == 1
        assert matches[0].employee_id == employee.id

        no_match = find_employees_with_skill(tenant, skill_name="Autre competence")
        assert no_match == []


def test_skill_level_is_idempotent_per_employee() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        employee = create_employee(
            tenant, first_name="Rina", last_name="Rakoto", hire_date=dt.date(2026, 1, 1)
        )
        set_employee_skill_level(employee, skill_name="Coupe", level="novice")
        set_employee_skill_level(employee, skill_name="Coupe", level="expert")
        assert PrsEmployeeSkill.objects.filter(employee=employee, skill_name="Coupe").count() == 1
        assert PrsEmployeeSkill.objects.get(employee=employee, skill_name="Coupe").level == "expert"


def test_document_expiry_alert_lifecycle() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        employee = create_employee(
            tenant, first_name="Rina", last_name="Rakoto", hire_date=dt.date(2026, 1, 1)
        )
        rh = UserFactory(email="rh-doc@example.com")
        document = add_employee_document(
            employee,
            code="visite_medicale",
            label="Visite médicale annuelle",
            expiry_date=dt.date.today() + dt.timedelta(days=10),
        )
        alerts = upcoming_document_alerts(tenant, within_days=30)
        assert document.id in [a.id for a in alerts]

        notify_document_alert(document, recipient=rh)
        document.refresh_from_db()
        assert document.notified_at is not None
        assert document.id not in [a.id for a in upcoming_document_alerts(tenant, within_days=30)]


def test_onboarding_checklist_is_triggered_and_completed() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        employee = create_employee(
            tenant, first_name="Toky", last_name="Rasoa", hire_date=dt.date(2026, 3, 1)
        )
        rh = UserFactory(email="rh-onb@example.com")
        tasks = trigger_onboarding_checklist(employee, responsible=rh)
        assert len(tasks) == len(DEFAULT_ONBOARDING_STEPS)

        done, total = onboarding_progress(employee)
        assert (done, total) == (0, len(DEFAULT_ONBOARDING_STEPS))

        complete_onboarding_task(tasks[0], completed_by=rh)
        done, total = onboarding_progress(employee)
        assert (done, total) == (1, len(DEFAULT_ONBOARDING_STEPS))

        # Idempotent : redeclencher ne duplique pas les taches.
        trigger_onboarding_checklist(employee, responsible=rh)
        assert PrsEmployeeTask.objects.filter(
            employee=employee, kind=PrsEmployeeTask.KIND_ONBOARDING
        ).count() == len(DEFAULT_ONBOARDING_STEPS)


def test_org_chart_svg_renders_hierarchy() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        manager = create_employee(
            tenant, first_name="Chef", last_name="Atelier", hire_date=dt.date(2020, 1, 1)
        )
        create_employee(
            tenant,
            first_name="Rina",
            last_name="Rakoto",
            hire_date=dt.date(2026, 1, 1),
            manager=manager,
        )
        svg = render_org_chart_svg(tenant)
        assert svg.startswith("<svg")
        assert "Chef" in svg
        assert "Rina" in svg


def test_org_chart_svg_empty_tenant_is_valid() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        svg = render_org_chart_svg(tenant)
        assert svg.startswith("<svg")
