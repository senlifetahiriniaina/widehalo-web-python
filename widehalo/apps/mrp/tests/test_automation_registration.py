"""AUTO3 — action `mrp.open_conformity_incident` enregistree dans
`core.services.automation_registry`."""

from __future__ import annotations

import uuid

import pytest

from apps.core.services.automation_registry import get_registered_action
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant
from apps.mrp.models import MrpCri
from apps.mrp.tests.factories import MrpWorkcenterFactory

pytestmark = pytest.mark.django_db


def test_mrp_open_conformity_incident_is_registered() -> None:
    action = get_registered_action("mrp.open_conformity_incident")
    assert action is not None
    assert action.module == "mrp"


def test_mrp_open_conformity_incident_adapter_creates_incident() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        workcenter = MrpWorkcenterFactory(tenant=tenant)
        action = get_registered_action("mrp.open_conformity_incident")
        assert action is not None

        incident_id = action.function(
            str(tenant.id),
            {
                "workcenter_id": str(workcenter.id),
                "pattern_id": str(uuid.uuid4()),
                "description": "Non-conformite constatee automatiquement",
            },
        )

        assert MrpCri.objects.filter(id=uuid.UUID(incident_id)).exists()
