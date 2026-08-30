"""AI7 — regle `mrp.conformity_incident_followup` enregistree dans
`core.services.advisor_rule_registry`."""

from __future__ import annotations

import pytest

from apps.core.services.advisor_rule_registry import get_advisor_rule
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant
from apps.mrp.models import MrpCri
from apps.mrp.tests.factories import MrpCriFactory

pytestmark = pytest.mark.django_db


def test_mrp_conformity_incident_followup_is_registered() -> None:
    rule = get_advisor_rule("mrp.conformity_incident_followup")
    assert rule is not None
    assert rule.module == "mrp"


def test_mrp_conformity_incident_followup_below_threshold_returns_nothing() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        MrpCriFactory(tenant=tenant, type=MrpCri.TYPE_QUALITY_INCIDENT, state=MrpCri.STATE_DRAFT)
        rule = get_advisor_rule("mrp.conformity_incident_followup")
        assert rule is not None
        assert rule.function(str(tenant.id), "consulter", "admin") == []


def test_mrp_conformity_incident_followup_at_threshold_suggests_automation() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        for _ in range(3):
            MrpCriFactory(
                tenant=tenant, type=MrpCri.TYPE_QUALITY_INCIDENT, state=MrpCri.STATE_DRAFT
            )
        rule = get_advisor_rule("mrp.conformity_incident_followup")
        assert rule is not None

        candidates = rule.function(str(tenant.id), "consulter", "admin")

    assert len(candidates) == 1
    assert candidates[0].target_module == "mrp"
    assert candidates[0].target_action_code == "mrp.open_conformity_incident"
    assert "3" in candidates[0].label
