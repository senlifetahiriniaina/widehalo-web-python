"""INT1 (chantier interactivite native inter-modules) : evenement
`feasibility.study_completed` (`services/simulation.py::complete_study`) et
action `feasibility.notify_study_completed` enregistree dans
`core.services.automation_registry`."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group

from apps.core.models.event import EventLog
from apps.core.models.notification import Notification
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.services.automation_registry import get_registered_action
from apps.core.tests.utils import use_tenant
from apps.feasibility.services.simulation import complete_study, create_study

pytestmark = pytest.mark.django_db


def test_complete_study_publishes_study_completed() -> None:
    tenant = Tenant.objects.create(code="FEA-INT1-T1", name="Feasibility INT1 Tenant 1")
    with use_tenant(tenant.id):
        study = create_study(tenant, name="Sac a main en cuir vegetal")
        completed = complete_study(study)
        assert completed.status == study.STATUS_COMPLETED

    event = EventLog.objects.get(event_type="feasibility.study_completed", tenant_id=str(tenant.id))
    assert event.payload["study_id"] == str(completed.id)


def test_notify_study_completed_action_is_registered() -> None:
    action = get_registered_action("feasibility.notify_study_completed")
    assert action is not None
    assert action.module == "feasibility"


def test_notify_study_completed_action_notifies_both_default_roles() -> None:
    tenant = Tenant.objects.create(code="FEA-INT1-NOTIF", name="Feasibility INT1 Notify Tenant")
    with use_tenant(tenant.id):
        direction_user = User.objects.create_user(
            email="fea-int1-direction@example.com", password="Str0ngPassw0rd!23"
        )
        commercial_user = User.objects.create_user(
            email="fea-int1-commercial@example.com", password="Str0ngPassw0rd!23"
        )
        direction_group, _ = Group.objects.get_or_create(name="direction")
        commercial_group, _ = Group.objects.get_or_create(name="resp_commercial")
        direction_user.groups.add(direction_group)
        commercial_user.groups.add(commercial_group)
        UserTenantMembership.objects.create(tenant=tenant, user=direction_user)
        UserTenantMembership.objects.create(tenant=tenant, user=commercial_user)

        action = get_registered_action("feasibility.notify_study_completed")
        assert action is not None
        action.function(str(tenant.id), {"note": "Etude terminee"})

        assert Notification.objects.filter(
            user=direction_user, notification_type="feasibility.study_completed"
        ).exists()
        assert Notification.objects.filter(
            user=commercial_user, notification_type="feasibility.study_completed"
        ).exists()
