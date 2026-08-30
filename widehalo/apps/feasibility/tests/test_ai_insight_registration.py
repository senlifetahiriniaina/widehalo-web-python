"""INT2 : `services.ai_insight_registration` — insight d'etudes de
faisabilite a marge simulee faible, enveloppe de `FeaStudyLine.computed_
margin_pct` (deja calcule par `services/simulation.py`)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.core.services.insight_source_registry import get_insight_source
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant
from apps.feasibility.models import FeaStudy
from apps.feasibility.services.ai_insight_registration import _low_margin_studies_insight
from apps.feasibility.tests.factories import FeaStudyFactory, FeaStudyLineFactory

pytestmark = pytest.mark.django_db


def test_source_is_registered_in_the_shared_registry() -> None:
    registered = get_insight_source("feasibility.low_margin_studies")
    assert registered is not None
    assert registered.module == "feasibility"
    assert registered.function is _low_margin_studies_insight


def test_no_insight_for_tenant_without_data() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        candidates = _low_margin_studies_insight(str(tenant.id))

    assert candidates == []


def test_no_insight_for_a_draft_study() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        study = FeaStudyFactory(tenant=tenant, status=FeaStudy.STATUS_DRAFT)
        FeaStudyLineFactory(tenant=tenant, study=study, computed_margin_pct=Decimal("-5"))

        candidates = _low_margin_studies_insight(str(tenant.id))

    assert candidates == []


def test_no_insight_for_a_completed_study_with_a_healthy_margin() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        study = FeaStudyFactory(tenant=tenant, status=FeaStudy.STATUS_COMPLETED)
        FeaStudyLineFactory(tenant=tenant, study=study, computed_margin_pct=Decimal("35"))

        candidates = _low_margin_studies_insight(str(tenant.id))

    assert candidates == []


def test_insight_fires_for_a_completed_study_with_a_low_margin_line() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        study = FeaStudyFactory(tenant=tenant, status=FeaStudy.STATUS_COMPLETED)
        FeaStudyLineFactory(tenant=tenant, study=study, computed_margin_pct=Decimal("-5"))

        candidates = _low_margin_studies_insight(str(tenant.id))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.category == "feasibility"
    assert candidate.source_modules == ["feasibility"]
    assert "1" in candidate.body
