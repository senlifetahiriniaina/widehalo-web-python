"""INT1 (chantier interactivite native inter-modules) : evenement
`crm.opportunity_stage_changed` (`services/pipeline.py::move_lead_to_stage`)
et action `crm.notify_role_of_opportunity` enregistree dans
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
from apps.crm.models import CrmLostReason, CrmPipeline, CrmStage
from apps.crm.services.leads import create_lead_quick
from apps.crm.services.pipeline import move_lead_to_stage

pytestmark = pytest.mark.django_db


@pytest.fixture
def pipeline_setup():
    tenant = Tenant.objects.create(code="CRM-INT1-PIPE", name="CRM INT1 Pipeline Tenant")
    with use_tenant(tenant.id):
        pipeline = CrmPipeline.objects.create(tenant=tenant, name="Ventes", is_default=True)
        new_stage = CrmStage.objects.create(
            tenant=tenant, pipeline=pipeline, code="nouveau", name="Nouveau", sequence=1
        )
        won_stage = CrmStage.objects.create(
            tenant=tenant,
            pipeline=pipeline,
            code="gagne",
            name="Gagne",
            sequence=2,
            probability=100,
            is_won=True,
        )
        lost_stage = CrmStage.objects.create(
            tenant=tenant,
            pipeline=pipeline,
            code="perdu",
            name="Perdu",
            sequence=3,
            is_lost=True,
        )
        lost_reason = CrmLostReason.objects.create(tenant=tenant, name="Prix trop eleve")
        return tenant, new_stage, won_stage, lost_stage, lost_reason


def test_move_lead_to_won_stage_publishes_opportunity_stage_changed(pipeline_setup) -> None:
    tenant, _new, won_stage, _lost, _reason = pipeline_setup
    with use_tenant(tenant.id):
        lead = create_lead_quick(tenant=tenant, name="Opportunite")
        moved = move_lead_to_stage(lead, won_stage)

    event = EventLog.objects.get(
        event_type="crm.opportunity_stage_changed", tenant_id=str(tenant.id)
    )
    assert event.payload["lead_id"] == str(moved.id)
    assert event.payload["is_won"] is True
    assert event.payload["is_lost"] is False


def test_move_lead_to_lost_stage_publishes_is_lost_true(pipeline_setup) -> None:
    tenant, _new, _won, lost_stage, lost_reason = pipeline_setup
    with use_tenant(tenant.id):
        lead = create_lead_quick(tenant=tenant, name="Opportunite")
        move_lead_to_stage(lead, lost_stage, lost_reason=lost_reason, comment="Trop cher")

    event = EventLog.objects.get(
        event_type="crm.opportunity_stage_changed", tenant_id=str(tenant.id)
    )
    assert event.payload["is_lost"] is True


def test_notify_role_of_opportunity_action_is_registered() -> None:
    action = get_registered_action("crm.notify_role_of_opportunity")
    assert action is not None
    assert action.module == "crm"


def test_notify_role_of_opportunity_action_notifies_role_members() -> None:
    tenant = Tenant.objects.create(code="CRM-INT1-NOTIF", name="CRM INT1 Notify Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="crm-int1-notify@example.com", password="Str0ngPassw0rd!23"
        )
        group, _ = Group.objects.get_or_create(name="resp_commercial")
        user.groups.add(group)
        UserTenantMembership.objects.create(tenant=tenant, user=user)

        action = get_registered_action("crm.notify_role_of_opportunity")
        assert action is not None
        action.function(
            str(tenant.id),
            {"role_code": "resp_commercial", "note": "Opportunite perdue"},
        )

        assert Notification.objects.filter(
            user=user, notification_type="crm.automation_alert"
        ).exists()
