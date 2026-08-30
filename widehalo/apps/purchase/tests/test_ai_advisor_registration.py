"""AI7 — regle `purchase.incident_followup` enregistree dans
`core.services.advisor_rule_registry`."""

from __future__ import annotations

import pytest

from apps.core.services.advisor_rule_registry import get_advisor_rule
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant
from apps.purchase.models import PurCri
from apps.purchase.tests.factories import PurCriFactory

pytestmark = pytest.mark.django_db


def test_purchase_incident_followup_is_registered() -> None:
    rule = get_advisor_rule("purchase.incident_followup")
    assert rule is not None
    assert rule.module == "purchase"


def test_purchase_incident_followup_below_threshold_returns_nothing() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        PurCriFactory(tenant=tenant, state=PurCri.STATE_DRAFT)
        rule = get_advisor_rule("purchase.incident_followup")
        assert rule is not None
        assert rule.function(str(tenant.id), "consulter", "admin") == []


def test_purchase_incident_followup_at_threshold_suggests_automation() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        for _ in range(3):
            PurCriFactory(tenant=tenant, state=PurCri.STATE_DRAFT)
        rule = get_advisor_rule("purchase.incident_followup")
        assert rule is not None

        candidates = rule.function(str(tenant.id), "consulter", "admin")

    assert len(candidates) == 1
    assert candidates[0].target_module == "purchase"
    assert candidates[0].target_action_code == "purchase.open_incident"
    assert "3" in candidates[0].label
