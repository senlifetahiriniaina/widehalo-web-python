from __future__ import annotations

import pytest

from apps.core.models.notification import Notification
from apps.core.models.risk import CATEGORY_PROJECT, RiskItem
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.automation_registry import get_registered_action
from apps.core.tests.utils import use_tenant
from apps.projects.services.projects import create_project

pytestmark = pytest.mark.django_db


@pytest.fixture
def automation_ctx():
    tenant = Tenant.objects.create(code="PRJ-AUTO-T1", name="Projects Automation Tenant")
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet automatise")
        user = User.objects.create_user(
            email="auto-owner@example.com", password="Str0ngPassw0rd!23"
        )
        project.owner = user
        project.save(update_fields=["owner"])
        yield tenant, project, user


def test_both_actions_are_registered() -> None:
    assert get_registered_action("projects.notify_project_owner") is not None
    assert get_registered_action("projects.flag_project_risk") is not None


def test_notify_project_owner_action_creates_a_notification(automation_ctx) -> None:
    tenant, project, user = automation_ctx
    action = get_registered_action("projects.notify_project_owner")
    assert action is not None
    with use_tenant(tenant.id):
        action.function(
            str(tenant.id),
            {"project_id": str(project.id), "notification_message": "Retard detecte"},
        )
        assert (
            Notification.objects.filter(
                user=user, notification_type="projects.automation_alert"
            ).count()
            == 1
        )


def test_flag_project_risk_action_creates_a_risk_item(automation_ctx) -> None:
    tenant, project, _user = automation_ctx
    action = get_registered_action("projects.flag_project_risk")
    assert action is not None
    with use_tenant(tenant.id):
        risk_id = action.function(
            str(tenant.id),
            {"project_id": str(project.id), "likelihood": 4, "impact": 5},
        )
        risk = RiskItem.objects.get(id=risk_id)
        assert risk.category == CATEGORY_PROJECT
        assert risk.score == 20
        assert risk.content_object == project


def test_actions_are_no_ops_when_project_has_no_owner(automation_ctx) -> None:
    tenant, project, _user = automation_ctx
    with use_tenant(tenant.id):
        project.owner = None
        project.save(update_fields=["owner"])

        notify_action = get_registered_action("projects.notify_project_owner")
        assert notify_action is not None
        notify_action.function(
            str(tenant.id), {"project_id": str(project.id), "notification_message": "x"}
        )
        assert (
            Notification.objects.filter(notification_type="projects.automation_alert").count() == 0
        )

        flag_action = get_registered_action("projects.flag_project_risk")
        assert flag_action is not None
        result = flag_action.function(
            str(tenant.id), {"project_id": str(project.id), "likelihood": 3, "impact": 3}
        )
        assert result is None
        assert RiskItem.objects.filter(category=CATEGORY_PROJECT).count() == 0
