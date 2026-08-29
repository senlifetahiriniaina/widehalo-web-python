from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.financing.models import FinForecastScenario
from apps.financing.services.forecast import (
    add_scenario_line,
    create_scenario,
    populate_cash_flow_from_treasury_forecast,
    populate_income_statement_from_payroll_projection,
)
from apps.payroll.models import PayContract
from apps.payroll.tests.factories import PayContractFactory

pytestmark = pytest.mark.django_db


def test_create_scenario_generates_reference() -> None:
    tenant = Tenant.objects.create(code="FIN-FCST1", name="Financing Forecast Tenant 1")
    with use_tenant(tenant.id):
        scenario = create_scenario(
            tenant,
            name="Scenario prudent",
            period_start=dt.date(2026, 1, 1),
            period_end=dt.date(2026, 12, 31),
        )
        assert scenario.reference.startswith("FINFCST-")


def test_create_scenario_rejects_inverted_period() -> None:
    tenant = Tenant.objects.create(code="FIN-FCST2", name="Financing Forecast Tenant 2")
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        create_scenario(
            tenant,
            name="Scenario invalide",
            period_start=dt.date(2026, 12, 31),
            period_end=dt.date(2026, 1, 1),
        )


def test_add_scenario_line_rejects_unknown_statement_type() -> None:
    tenant = Tenant.objects.create(code="FIN-FCST3", name="Financing Forecast Tenant 3")
    with use_tenant(tenant.id):
        scenario = create_scenario(
            tenant,
            name="Scenario",
            period_start=dt.date(2026, 1, 1),
            period_end=dt.date(2026, 12, 31),
        )
        with pytest.raises(ValidationError):
            add_scenario_line(
                scenario,
                statement_type="not_a_real_statement",
                label="x",
                period="2026-01",
                amount_mga=Decimal("1"),
            )


def test_populate_income_statement_from_payroll_projection() -> None:
    tenant = Tenant.objects.create(code="FIN-FCST4", name="Financing Forecast Tenant 4")
    with use_tenant(tenant.id):
        PayContractFactory(
            tenant=tenant, wage_base=Decimal("1000000"), state=PayContract.STATE_ACTIVE
        )
        scenario = create_scenario(
            tenant,
            name="Scenario paie",
            period_start=dt.date(2026, 1, 1),
            period_end=dt.date(2026, 12, 31),
        )
        lines = populate_income_statement_from_payroll_projection(scenario, tenant, months=3)
        assert len(lines) == 3
        assert all(line.amount_mga < 0 for line in lines)
        assert lines[0].period == "2026-01"
        assert lines[2].period == "2026-03"

        # Regeneration : ne duplique jamais les lignes `payroll_projection`.
        lines_again = populate_income_statement_from_payroll_projection(scenario, tenant, months=3)
        assert scenario.lines.filter(source="payroll_projection").count() == len(lines_again)


def test_populate_cash_flow_from_treasury_forecast() -> None:
    tenant = Tenant.objects.create(code="FIN-FCST5", name="Financing Forecast Tenant 5")
    with use_tenant(tenant.id):
        scenario = create_scenario(
            tenant,
            name="Scenario tresorerie",
            period_start=dt.date(2026, 1, 1),
            period_end=dt.date(2026, 12, 31),
        )
        lines = populate_cash_flow_from_treasury_forecast(
            scenario, tenant, as_of_date=dt.date(2026, 1, 1), horizon_days=14
        )
        assert len(lines) >= 1
        assert all(line.statement_type == FinForecastScenario.STATEMENT_CASH_FLOW for line in lines)
