"""INT2 : `services.ai_advisor_registration` — regle `crm.stagnant_
opportunity_followup` enregistree dans `core.services.advisor_rule_
registry`, reutilise directement `_check_stagnant_opportunities`."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.services.advisor_rule_registry import get_advisor_rule
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant
from apps.crm.services.ai_advisor_registration import _advise_on_crm
from apps.crm.tests.factories import CrmLeadFactory

pytestmark = pytest.mark.django_db


def test_rule_is_registered_in_the_shared_registry() -> None:
    rule = get_advisor_rule("crm.stagnant_opportunity_followup")
    assert rule is not None
    assert rule.module == "crm"
    assert rule.function is _advise_on_crm


def test_rule_returns_nothing_for_tenant_without_data() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        candidates = _advise_on_crm(str(tenant.id), "consulter", "resp_commercial")

    assert candidates == []


def test_rule_suggests_followup_for_stagnant_opportunities() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        lead = CrmLeadFactory(tenant=tenant)
        lead.created_at = timezone.now() - timedelta(days=30)
        lead.save(update_fields=["created_at"])

        candidates = _advise_on_crm(str(tenant.id), "consulter", "resp_commercial")

    assert len(candidates) == 1
    assert candidates[0].target_module == "crm"
    assert candidates[0].target_action_code == "crm.notify_role_of_opportunity"
    assert "1" in candidates[0].label
