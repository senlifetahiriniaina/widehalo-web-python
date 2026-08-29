from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.financing.models import FinGuarantee
from apps.financing.services.guarantees import add_guarantee, check_guarantee_coverage
from apps.financing.services.loan_applications import create_loan_application

pytestmark = pytest.mark.django_db


def _application(tenant: Tenant, amount: Decimal = Decimal("10000000")):
    return create_loan_application(
        tenant,
        type="fonctionnement",
        amount_requested_mga=amount,
        duration_months=12,
    )


def test_add_guarantee_rejects_non_positive_value() -> None:
    tenant = Tenant.objects.create(code="FIN-GUAR1", name="Financing Guarantee Tenant 1")
    with use_tenant(tenant.id):
        application = _application(tenant)
        with pytest.raises(ValidationError):
            add_guarantee(
                application,
                type=FinGuarantee.GUARANTEE_TYPE_MORTGAGE,
                estimated_value_mga=Decimal("0"),
            )


def test_guarantee_coverage_below_threshold() -> None:
    tenant = Tenant.objects.create(code="FIN-GUAR2", name="Financing Guarantee Tenant 2")
    with use_tenant(tenant.id):
        application = _application(tenant, amount=Decimal("10000000"))
        add_guarantee(
            application,
            type=FinGuarantee.GUARANTEE_TYPE_MORTGAGE,
            estimated_value_mga=Decimal("5000000"),
        )
        coverage = check_guarantee_coverage(application)
        assert coverage["is_covered"] is False
        assert coverage["required_value_mga"] == Decimal("12000000.00")


def test_guarantee_coverage_reaches_120_percent() -> None:
    tenant = Tenant.objects.create(code="FIN-GUAR3", name="Financing Guarantee Tenant 3")
    with use_tenant(tenant.id):
        application = _application(tenant, amount=Decimal("10000000"))
        add_guarantee(
            application,
            type=FinGuarantee.GUARANTEE_TYPE_MORTGAGE,
            estimated_value_mga=Decimal("8000000"),
        )
        add_guarantee(
            application,
            type=FinGuarantee.GUARANTEE_TYPE_PLEDGE,
            estimated_value_mga=Decimal("4200000"),
        )
        coverage = check_guarantee_coverage(application)
        assert coverage["is_covered"] is True
        assert coverage["total_guarantee_value_mga"] == Decimal("12200000")
