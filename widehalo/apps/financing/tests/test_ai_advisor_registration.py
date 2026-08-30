"""INT2 : `services.ai_advisor_registration` — regle `financing.guarantee_
coverage_advisor`, enveloppe directe de `services.guarantees.check_
guarantee_coverage` (FIN2, regle de couverture >= 120% du credit)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.core.services.advisor_rule_registry import get_advisor_rule
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant
from apps.financing.models import FinLoanApplication
from apps.financing.services.ai_advisor_registration import _advise_on_financing
from apps.financing.tests.factories import FinGuaranteeFactory, FinLoanApplicationFactory

pytestmark = pytest.mark.django_db


def test_rule_is_registered_in_the_shared_registry() -> None:
    rule = get_advisor_rule("financing.guarantee_coverage_advisor")
    assert rule is not None
    assert rule.module == "financing"
    assert rule.function is _advise_on_financing


def test_rule_returns_nothing_for_tenant_without_data() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        candidates = _advise_on_financing(str(tenant.id), "consulter", "resp_financement")

    assert candidates == []


def test_rule_ignores_a_sufficiently_covered_application() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        application = FinLoanApplicationFactory(
            tenant=tenant,
            amount_requested_mga=Decimal("10000000"),
            state=FinLoanApplication.STATE_SUBMITTED,
        )
        FinGuaranteeFactory(
            tenant=tenant,
            loan_application=application,
            estimated_value_mga=Decimal("12000000"),
        )

        candidates = _advise_on_financing(str(tenant.id), "consulter", "resp_financement")

    assert candidates == []


def test_rule_suggests_completing_guarantees_when_undercovered() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        FinLoanApplicationFactory(
            tenant=tenant,
            amount_requested_mga=Decimal("10000000"),
            state=FinLoanApplication.STATE_SUBMITTED,
        )

        candidates = _advise_on_financing(str(tenant.id), "consulter", "resp_financement")

    # Aucune surete du tout => couverture 0%, largement sous 120%.
    assert len(candidates) == 1
    assert candidates[0].target_module == "financing"
    assert "0" in candidates[0].label


def test_rule_ignores_a_rejected_application_even_if_undercovered() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        FinLoanApplicationFactory(
            tenant=tenant,
            amount_requested_mga=Decimal("10000000"),
            state=FinLoanApplication.STATE_REJECTED,
        )

        candidates = _advise_on_financing(str(tenant.id), "consulter", "resp_financement")

    assert candidates == []
