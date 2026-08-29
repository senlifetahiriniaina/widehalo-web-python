from __future__ import annotations

import pytest

from apps.core.models.tenant import Tenant
from apps.core.services.reports_registry import register_report
from apps.core.tests.utils import use_tenant
from apps.reporting.models import RptDefinition
from apps.reporting.services.catalog import sync_report_definitions

pytestmark = pytest.mark.django_db


def _rows(params: dict, actor) -> list[dict]:  # noqa: ANN001
    return [{"a": 1}]


def test_sync_report_definitions_creates_one_row_per_registered_report() -> None:
    register_report(
        code="RPT-TEST-SYNC",
        module="core",
        label="Test sync",
        permission="core.view_tenant",
        render_rows=_rows,
    )
    tenant = Tenant.objects.create(code="RPT-SYNC", name="Reporting Sync Tenant")
    with use_tenant(tenant.id):
        count = sync_report_definitions(tenant)
        assert count >= 1
        definition = RptDefinition.objects.get(tenant=tenant, code="RPT-TEST-SYNC")
        assert definition.module == "core"
        assert definition.is_enabled is True


def test_sync_report_definitions_does_not_reset_manual_disable() -> None:
    register_report(
        code="RPT-TEST-DISABLE",
        module="core",
        label="Test disable",
        permission="core.view_tenant",
        render_rows=_rows,
    )
    tenant = Tenant.objects.create(code="RPT-DISABLE", name="Reporting Disable Tenant")
    with use_tenant(tenant.id):
        sync_report_definitions(tenant)
        definition = RptDefinition.objects.get(tenant=tenant, code="RPT-TEST-DISABLE")
        definition.is_enabled = False
        definition.save(update_fields=["is_enabled"])

        sync_report_definitions(tenant)
        definition.refresh_from_db()
        assert definition.is_enabled is False
