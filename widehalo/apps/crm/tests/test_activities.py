from __future__ import annotations

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.crm.models import CrmPipeline, CrmStage
from apps.crm.services.activities import complete_activity, lead_timeline, log_activity
from apps.crm.services.leads import create_lead_quick

pytestmark = pytest.mark.django_db


@pytest.fixture
def lead_setup():
    tenant = Tenant.objects.create(code="CRM-ACT", name="CRM Activity Tenant")
    with use_tenant(tenant.id):
        pipeline = CrmPipeline.objects.create(tenant=tenant, name="Ventes", is_default=True)
        CrmStage.objects.create(
            tenant=tenant, pipeline=pipeline, code="nouveau", name="Nouveau", sequence=1
        )
        lead = create_lead_quick(tenant=tenant, name="Opportunite")
        return tenant, lead


def test_log_activity_attaches_to_lead(lead_setup) -> None:
    tenant, lead = lead_setup
    with use_tenant(tenant.id):
        activity = log_activity(lead, activity_type="call", subject="Premier contact")
        assert activity.lead_id == lead.id
        assert activity.done_at is None


def test_complete_activity_sets_done_at(lead_setup) -> None:
    tenant, lead = lead_setup
    with use_tenant(tenant.id):
        activity = log_activity(lead, activity_type="visit", subject="Visite showroom")
        completed = complete_activity(activity)
        assert completed.done_at is not None


def test_lead_timeline_orders_most_recent_first(lead_setup) -> None:
    tenant, lead = lead_setup
    with use_tenant(tenant.id):
        first = log_activity(lead, activity_type="email", subject="Envoi devis")
        second = log_activity(lead, activity_type="follow_up", subject="Relance")
        timeline = lead_timeline(lead)
        assert timeline[0].id == second.id
        assert timeline[1].id == first.id


def test_lead_timeline_empty_for_new_lead(lead_setup) -> None:
    tenant, lead = lead_setup
    with use_tenant(tenant.id):
        assert lead_timeline(lead) == []
