from __future__ import annotations

from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.crm.models import CrmPipeline, CrmStage
from apps.crm.services.activities import log_activity
from apps.crm.services.leads import create_lead_quick
from apps.crm.services.scoring import compute_lead_score, whatsapp_contact_link

pytestmark = pytest.mark.django_db


@pytest.fixture
def scoring_setup():
    tenant = Tenant.objects.create(code="CRM-SCORE", name="CRM Score Tenant")
    with use_tenant(tenant.id):
        pipeline = CrmPipeline.objects.create(tenant=tenant, name="Ventes", is_default=True)
        CrmStage.objects.create(
            tenant=tenant, pipeline=pipeline, code="nouveau", name="Nouveau", sequence=1
        )
        return tenant


def test_score_increases_with_expected_revenue(scoring_setup) -> None:
    tenant = scoring_setup
    with use_tenant(tenant.id):
        small = create_lead_quick(
            tenant=tenant, name="Petit", expected_revenue_mga=Decimal(1_000_000)
        )
        big = create_lead_quick(
            tenant=tenant, name="Gros", expected_revenue_mga=Decimal(20_000_000)
        )
        assert compute_lead_score(big) > compute_lead_score(small)


def test_score_increases_with_activity_history(scoring_setup) -> None:
    tenant = scoring_setup
    with use_tenant(tenant.id):
        lead = create_lead_quick(tenant=tenant, name="Suivi")
        before = compute_lead_score(lead)
        log_activity(lead, activity_type="call", subject="Appel 1")
        log_activity(lead, activity_type="email", subject="Email 1")
        after = compute_lead_score(lead)
        assert after > before


def test_score_capped_at_100(scoring_setup) -> None:
    tenant = scoring_setup
    with use_tenant(tenant.id):
        lead = create_lead_quick(
            tenant=tenant,
            name="Enorme",
            expected_revenue_mga=Decimal(999_999_999),
            probability=100,
        )
        for i in range(20):
            log_activity(lead, activity_type="call", subject=f"Appel {i}")
        assert compute_lead_score(lead) == 100


def test_whatsapp_link_none_without_phone(scoring_setup) -> None:
    tenant = scoring_setup
    with use_tenant(tenant.id):
        lead = create_lead_quick(tenant=tenant, name="Sans telephone")
        assert whatsapp_contact_link(lead) is None


def test_whatsapp_link_strips_non_digits(scoring_setup) -> None:
    tenant = scoring_setup
    with use_tenant(tenant.id):
        lead = create_lead_quick(tenant=tenant, name="Avec telephone", phone="+261 34 12 345 67")
        link = whatsapp_contact_link(lead)
        assert link is not None
        assert link.startswith("https://wa.me/261341234567?text=")
