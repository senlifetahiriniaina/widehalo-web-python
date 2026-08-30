"""INT2 : `services.ai_anomaly_registration` — anomalie d'opportunite
stagnante, jamais fabriquee sans une reelle absence d'activite recente."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.services.anomaly_registry import (
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    get_anomaly_check,
)
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant
from apps.crm.services.ai_anomaly_registration import _check_stagnant_opportunities
from apps.crm.tests.factories import CrmActivityFactory, CrmLeadFactory

pytestmark = pytest.mark.django_db


def test_check_is_registered_in_the_shared_registry() -> None:
    registered = get_anomaly_check("crm.stagnant_opportunity")
    assert registered is not None
    assert registered.module == "crm"
    assert registered.function is _check_stagnant_opportunities


def test_check_returns_empty_list_for_tenant_without_data() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        candidates = _check_stagnant_opportunities(str(tenant.id))

    assert candidates == []


def test_check_ignores_a_recently_active_lead() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        lead = CrmLeadFactory(tenant=tenant)
        CrmActivityFactory(tenant=tenant, lead=lead)

        candidates = _check_stagnant_opportunities(str(tenant.id))

    assert candidates == []


def test_check_flags_a_lead_without_recent_activity() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        lead = CrmLeadFactory(tenant=tenant)
        lead.created_at = timezone.now() - timedelta(days=25)
        lead.save(update_fields=["created_at"])

        candidates = _check_stagnant_opportunities(str(tenant.id))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.content_type_label == "crm.crmlead"
    assert candidate.object_id == str(lead.id)
    assert candidate.severity == SEVERITY_MEDIUM
    assert lead.name in candidate.description


def test_check_flags_high_severity_for_a_long_stagnant_lead() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        lead = CrmLeadFactory(tenant=tenant)
        lead.created_at = timezone.now() - timedelta(days=50)
        lead.save(update_fields=["created_at"])

        candidates = _check_stagnant_opportunities(str(tenant.id))

    assert len(candidates) == 1
    assert candidates[0].severity == SEVERITY_HIGH


def test_check_ignores_a_won_lead_even_without_activity() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        lead = CrmLeadFactory(tenant=tenant, won_at=timezone.now())
        lead.created_at = timezone.now() - timedelta(days=50)
        lead.save(update_fields=["created_at"])

        candidates = _check_stagnant_opportunities(str(tenant.id))

    assert candidates == []


def test_check_uses_most_recent_activity_not_lead_creation() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        lead = CrmLeadFactory(tenant=tenant)
        lead.created_at = timezone.now() - timedelta(days=50)
        lead.save(update_fields=["created_at"])
        # Une activite recente rend l'opportunite non stagnante malgre une
        # creation ancienne.
        CrmActivityFactory(tenant=tenant, lead=lead)

        candidates = _check_stagnant_opportunities(str(tenant.id))

    assert candidates == []
