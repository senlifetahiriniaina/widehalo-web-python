"""INT2 : `services.ai_insight_registration` — insight de taux de
conversion bas, enveloppe de `services.reports.conversion_rate` (CRM-CONV),
jamais fabrique sur un trop petit echantillon."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.core.services.insight_source_registry import get_insight_source
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant
from apps.crm.services.ai_insight_registration import _pipeline_conversion_insight
from apps.crm.tests.factories import CrmLeadFactory, CrmPipelineFactory

pytestmark = pytest.mark.django_db


def test_source_is_registered_in_the_shared_registry() -> None:
    registered = get_insight_source("crm.pipeline_conversion_trend")
    assert registered is not None
    assert registered.module == "crm"
    assert registered.function is _pipeline_conversion_insight


def test_no_insight_for_tenant_without_data() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        candidates = _pipeline_conversion_insight(str(tenant.id))

    assert candidates == []


def test_no_insight_below_the_minimum_sample_size() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        pipeline = CrmPipelineFactory(tenant=tenant)
        # Un seul lead perdu : echantillon trop petit pour un signal fiable.
        CrmLeadFactory(tenant=tenant, pipeline=pipeline, lost_at=timezone.now())

        candidates = _pipeline_conversion_insight(str(tenant.id))

    assert candidates == []


def test_insight_fires_on_a_low_conversion_rate() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        pipeline = CrmPipelineFactory(tenant=tenant)
        CrmLeadFactory(tenant=tenant, pipeline=pipeline, won_at=timezone.now())
        for _ in range(4):
            CrmLeadFactory(tenant=tenant, pipeline=pipeline, lost_at=timezone.now())

        candidates = _pipeline_conversion_insight(str(tenant.id))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.category == "crm"
    assert candidate.source_modules == ["crm"]
    assert pipeline.name in candidate.title


def test_no_insight_on_a_high_conversion_rate() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        pipeline = CrmPipelineFactory(tenant=tenant)
        for _ in range(4):
            CrmLeadFactory(tenant=tenant, pipeline=pipeline, won_at=timezone.now())
        CrmLeadFactory(tenant=tenant, pipeline=pipeline, lost_at=timezone.now())

        candidates = _pipeline_conversion_insight(str(tenant.id))

    assert candidates == []
