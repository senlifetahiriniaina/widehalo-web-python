"""Factories factory_boy pour les modeles du module `financing` — une par
modele concret (couche T1 du plan de durcissement, CDC §14 couches)."""

from __future__ import annotations

from decimal import Decimal

import factory

from apps.financing.models import FinFinancingPlanLine, FinLoanApplication


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
