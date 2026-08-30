"""INT2 : `services.ai_anomaly_registration` — anomalie de dossier douanier
ouvert depuis trop longtemps (`LogCustomsFile.state`/`opened_at`, LOG5)."""

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
from apps.logistics.models import LogCustomsFile
from apps.logistics.services.ai_anomaly_registration import _check_customs_files_at_risk
from apps.logistics.tests.factories import LogCustomsFileFactory

pytestmark = pytest.mark.django_db


def test_check_is_registered_in_the_shared_registry() -> None:
    registered = get_anomaly_check("logistics.customs_file_at_risk")
    assert registered is not None
    assert registered.module == "logistics"
    assert registered.function is _check_customs_files_at_risk


def test_check_returns_empty_list_for_tenant_without_data() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        candidates = _check_customs_files_at_risk(str(tenant.id))

    assert candidates == []


def test_check_ignores_a_recently_opened_file() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        LogCustomsFileFactory(tenant=tenant, opened_at=timezone.now().date())

        candidates = _check_customs_files_at_risk(str(tenant.id))

    assert candidates == []


def test_check_ignores_a_cleared_file_even_if_old() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        LogCustomsFileFactory(
            tenant=tenant,
            state=LogCustomsFile.STATE_CLEARED,
            opened_at=timezone.now().date() - timedelta(days=30),
        )

        candidates = _check_customs_files_at_risk(str(tenant.id))

    assert candidates == []


def test_check_flags_a_file_open_beyond_the_threshold() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        customs_file = LogCustomsFileFactory(
            tenant=tenant, opened_at=timezone.now().date() - timedelta(days=20)
        )

        candidates = _check_customs_files_at_risk(str(tenant.id))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.content_type_label == "logistics.logcustomsfile"
    assert candidate.object_id == str(customs_file.id)
    assert candidate.severity == SEVERITY_MEDIUM


def test_check_flags_high_severity_for_a_very_old_file() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        LogCustomsFileFactory(tenant=tenant, opened_at=timezone.now().date() - timedelta(days=40))

        candidates = _check_customs_files_at_risk(str(tenant.id))

    assert len(candidates) == 1
    assert candidates[0].severity == SEVERITY_HIGH
