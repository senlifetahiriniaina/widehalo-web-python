"""INT2 : `services.ai_anomaly_registration` — anomalie de validation ECO
en attente prolongee, reutilise directement les `ApprovalRequest` DEJA
crees par `services.eco.enforce_eco_validation` (PAT-ECO1)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from apps.core.models.workflow import ApprovalRequest, ApprovalRule
from apps.core.services.anomaly_registry import (
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    get_anomaly_check,
)
from apps.core.tests.factories import TenantFactory, UserFactory
from apps.core.tests.utils import use_tenant
from apps.patronage.models import PatPattern
from apps.patronage.services.ai_anomaly_registration import (
    _check_pending_eco_validations,
)
from apps.patronage.services.eco import RULE_NAME
from apps.patronage.tests.factories import PatPatternFactory

pytestmark = pytest.mark.django_db


def _create_pending_request(tenant, pattern, requester, *, age_days: int) -> ApprovalRequest:
    content_type = ContentType.objects.get_for_model(PatPattern)
    rule = ApprovalRule.objects.create(
        tenant=tenant,
        content_type=content_type,
        name=RULE_NAME,
        approver_role="resp_production",
        sequence_order=1,
    )
    request = ApprovalRequest.objects.create(
        rule=rule,
        content_type=content_type,
        object_id=str(pattern.id),
        requested_by=requester,
        status=ApprovalRequest.STATUS_PENDING,
    )
    request.created_at = timezone.now() - timedelta(days=age_days)
    request.save(update_fields=["created_at"])
    return request


def test_check_is_registered_in_the_shared_registry() -> None:
    registered = get_anomaly_check("patronage.pending_eco_validation")
    assert registered is not None
    assert registered.module == "patronage"
    assert registered.function is _check_pending_eco_validations


def test_check_returns_empty_list_for_tenant_without_data() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        candidates = _check_pending_eco_validations(str(tenant.id))

    assert candidates == []


def test_check_ignores_a_recent_pending_request() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        requester = UserFactory()
        pattern = PatPatternFactory(tenant=tenant)
        _create_pending_request(tenant, pattern, requester, age_days=1)

        candidates = _check_pending_eco_validations(str(tenant.id))

    assert candidates == []


def test_check_flags_a_pending_request_beyond_the_threshold() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        requester = UserFactory()
        pattern = PatPatternFactory(tenant=tenant)
        _create_pending_request(tenant, pattern, requester, age_days=10)

        candidates = _check_pending_eco_validations(str(tenant.id))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.content_type_label == "patronage.patpattern"
    assert candidate.object_id == str(pattern.id)
    assert candidate.severity == SEVERITY_MEDIUM


def test_check_flags_high_severity_for_a_very_old_pending_request() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        requester = UserFactory()
        pattern = PatPatternFactory(tenant=tenant)
        _create_pending_request(tenant, pattern, requester, age_days=20)

        candidates = _check_pending_eco_validations(str(tenant.id))

    assert len(candidates) == 1
    assert candidates[0].severity == SEVERITY_HIGH


def test_check_ignores_an_approved_request() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        requester = UserFactory()
        pattern = PatPatternFactory(tenant=tenant)
        request = _create_pending_request(tenant, pattern, requester, age_days=10)
        request.status = ApprovalRequest.STATUS_APPROVED
        request.save(update_fields=["status"])

        candidates = _check_pending_eco_validations(str(tenant.id))

    assert candidates == []
