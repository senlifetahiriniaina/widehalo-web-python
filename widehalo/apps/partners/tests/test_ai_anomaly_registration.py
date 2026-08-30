"""INT2 : `services.ai_anomaly_registration` — anomalie de doublon
partenaire non resolu, reutilise directement `DuplicateAlert` (jamais un
nouveau calcul de similarite)."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.core.services.anomaly_registry import SEVERITY_MEDIUM, get_anomaly_check
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant
from apps.partners.services.ai_anomaly_registration import (
    _check_unresolved_duplicate_alerts,
)
from apps.partners.tests.factories import DuplicateAlertFactory

pytestmark = pytest.mark.django_db


def test_check_is_registered_in_the_shared_registry() -> None:
    registered = get_anomaly_check("partners.unresolved_duplicate_alert")
    assert registered is not None
    assert registered.module == "partners"
    assert registered.function is _check_unresolved_duplicate_alerts


def test_check_returns_empty_list_for_tenant_without_data() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        candidates = _check_unresolved_duplicate_alerts(str(tenant.id))

    assert candidates == []


def test_check_ignores_a_resolved_alert() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        DuplicateAlertFactory(tenant=tenant, resolved_at=timezone.now())

        candidates = _check_unresolved_duplicate_alerts(str(tenant.id))

    assert candidates == []


def test_check_flags_an_unresolved_alert() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        alert = DuplicateAlertFactory(tenant=tenant)

        candidates = _check_unresolved_duplicate_alerts(str(tenant.id))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.content_type_label == "partners.duplicatealert"
    assert candidate.object_id == str(alert.id)
    assert candidate.severity == SEVERITY_MEDIUM
    assert alert.partner.name in candidate.description
    assert alert.duplicate_of.name in candidate.description
