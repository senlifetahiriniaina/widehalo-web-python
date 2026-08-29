"""Factories factory_boy pour les modeles du module `financing` — une par
modele concret (couche T1 du plan de durcissement, CDC §14 couches)."""

from __future__ import annotations

import datetime
from decimal import Decimal

import factory

from apps.financing.models import (
    FinFinancingPlanLine,
    FinForecastScenario,
    FinForecastScenarioLine,
    FinGuarantee,
    FinLoanApplication,
)


class FinLoanApplicationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FinLoanApplication

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    type = FinLoanApplication.LOAN_TYPE_OPERATING  # noqa: A003
    amount_requested_mga = Decimal("10000000")
    duration_months = 12
    bank_name = "Banque Test"


class FinFinancingPlanLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FinFinancingPlanLine

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    loan_application = factory.SubFactory(
        FinLoanApplicationFactory, tenant=factory.SelfAttribute("..tenant")
    )
    source = FinFinancingPlanLine.SOURCE_OWN_FUNDS
    amount_mga = Decimal("3000000")


class FinForecastScenarioFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FinForecastScenario

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Scenario {n}")
    period_start = datetime.date(2026, 1, 1)
    period_end = datetime.date(2026, 12, 31)


class FinForecastScenarioLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FinForecastScenarioLine

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    scenario = factory.SubFactory(
        FinForecastScenarioFactory, tenant=factory.SelfAttribute("..tenant")
    )
    statement_type = FinForecastScenario.STATEMENT_INCOME
    label = "Chiffre d'affaires previsionnel"
    period = "2026-01"
    amount_mga = Decimal("5000000")


class FinGuaranteeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FinGuarantee

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    loan_application = factory.SubFactory(
        FinLoanApplicationFactory, tenant=factory.SelfAttribute("..tenant")
    )
    type = FinGuarantee.GUARANTEE_TYPE_MORTGAGE  # noqa: A003
    estimated_value_mga = Decimal("12000000")
