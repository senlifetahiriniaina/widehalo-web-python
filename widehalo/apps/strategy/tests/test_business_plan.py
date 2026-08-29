from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.services.reports_registry import get_registered_report
from apps.core.tenant_context import activate_tenant
from apps.core.tests.utils import use_tenant
from apps.strategy.models import StgObjective
from apps.strategy.services.benchmarks import create_note
from apps.strategy.services.business_plan import generate_business_plan_pdf
from apps.strategy.services.objectives import add_key_result, create_objective, record_check_in

pytestmark = pytest.mark.django_db


def test_generate_business_plan_pdf_assembles_all_sections() -> None:
    tenant = Tenant.objects.create(code="STG-BP1", name="Business Plan Tenant")
    with use_tenant(tenant.id):
        objective = create_objective(
            tenant,
            title="Croissance CA 2026",
            level=StgObjective.LEVEL_COMPANY,
            period_start=datetime.date(2026, 6, 1),
            period_end=datetime.date(2026, 6, 30),
        )
        key_result = add_key_result(
            objective, metric_name="CA MGA", target_value=Decimal("1000000")
        )
        record_check_in(key_result, date=datetime.date(2026, 6, 15), value=Decimal("500000"))
        create_note(tenant, title="Synthese direction", body="Bon trimestre.", objective=objective)

        pdf_bytes = generate_business_plan_pdf(tenant, "2026-06")

        assert pdf_bytes.startswith(b"%PDF")


def test_strategy_bp_registered_render_pdf_only_in_reporting_catalog() -> None:
    """`STRATEGY-BP` est enregistre `render_pdf`-only (pas de `render_rows`)
    — meme patron que ACC-FAC/PAY-BULL."""
    report = get_registered_report("STRATEGY-BP")
    assert report is not None
    assert report.supports_pdf()
    assert not report.supports_rows()


def test_strategy_bp_adapter_generates_pdf_via_registry() -> None:
    tenant = Tenant.objects.create(code="STG-BP2", name="Business Plan Tenant 2")
    with activate_tenant(tenant.id):
        report = get_registered_report("STRATEGY-BP")
        assert report is not None
        assert report.render_pdf is not None
        pdf_bytes = report.render_pdf({"period": "2026-06"}, None)
        assert pdf_bytes.startswith(b"%PDF")
