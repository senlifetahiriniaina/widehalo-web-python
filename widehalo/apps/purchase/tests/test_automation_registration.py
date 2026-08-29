"""AUTO3 — action `purchase.open_incident` enregistree dans
`core.services.automation_registry`."""

from __future__ import annotations

import uuid

import pytest

from apps.core.services.automation_registry import get_registered_action
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant
from apps.partners.tests.factories import PartnerFactory
from apps.purchase.models import PurCri

pytestmark = pytest.mark.django_db


def test_purchase_open_incident_is_registered() -> None:
    action = get_registered_action("purchase.open_incident")
    assert action is not None
    assert action.module == "purchase"


def test_purchase_open_incident_adapter_creates_incident() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        partner = PartnerFactory(tenant=tenant)
        action = get_registered_action("purchase.open_incident")
        assert action is not None

        incident_id = action.function(
            str(tenant.id),
            {"partner_id": str(partner.id), "description": "Ecart de mesure automatique"},
        )

        assert PurCri.objects.filter(id=uuid.UUID(incident_id)).exists()
