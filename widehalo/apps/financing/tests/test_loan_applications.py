from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.financing.models import FinLoanApplication
from apps.financing.services.loan_applications import (
    add_financing_plan_line,
    create_loan_application,
    decide_application,
    financing_plan_total,
    submit_application,
    validate_financing_plan_balance,
)

pytestmark = pytest.mark.django_db


def test_create_loan_application_generates_reference() -> None:
    tenant = Tenant.objects.create(code="FIN-T1", name="Financing Tenant 1")
    with use_tenant(tenant.id):
        application = create_loan_application(
            tenant,
            type=FinLoanApplication.LOAN_TYPE_INVESTMENT_LT,
            amount_requested_mga=Decimal("50000000"),
            duration_months=36,
        )
        assert application.reference.startswith("FINLOAN-")
        assert application.state == FinLoanApplication.STATE_DRAFT


def test_create_loan_application_rejects_non_positive_amount() -> None:
    tenant = Tenant.objects.create(code="FIN-T2", name="Financing Tenant 2")
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        create_loan_application(
            tenant,
            type=FinLoanApplication.LOAN_TYPE_OPERATING,
            amount_requested_mga=Decimal("0"),
            duration_months=12,
        )


def test_financing_plan_balance_and_submission_flow() -> None:
    tenant = Tenant.objects.create(code="FIN-T3", name="Financing Tenant 3")
    with use_tenant(tenant.id):
        application = create_loan_application(
            tenant,
            type=FinLoanApplication.LOAN_TYPE_INVESTMENT_ST_MT,
            amount_requested_mga=Decimal("10000000"),
            duration_months=24,
        )
        assert validate_financing_plan_balance(application) is False

        add_financing_plan_line(application, source="fonds_propres", amount_mga=Decimal("3000000"))
        add_financing_plan_line(
            application, source="emprunt_sollicite", amount_mga=Decimal("7000000")
        )
        assert financing_plan_total(application) == Decimal("10000000")
        assert validate_financing_plan_balance(application) is True

        submit_application(application)
        application.refresh_from_db()
        assert application.state == FinLoanApplication.STATE_SUBMITTED
        assert application.submission_date is not None

        # Impossible d'ajouter une ligne sur un dossier deja soumis.
        with pytest.raises(ValidationError):
            add_financing_plan_line(application, source="autre", amount_mga=Decimal("1"))

        decide_application(application, accepted=True)
        application.refresh_from_db()
        assert application.state == FinLoanApplication.STATE_ACCEPTED
        assert application.decision_date is not None


def test_decide_application_requires_submitted_state() -> None:
    tenant = Tenant.objects.create(code="FIN-T4", name="Financing Tenant 4")
    with use_tenant(tenant.id):
        application = create_loan_application(
            tenant,
            type=FinLoanApplication.LOAN_TYPE_OPERATING,
            amount_requested_mga=Decimal("1000000"),
            duration_months=6,
        )
        with pytest.raises(ValidationError):
            decide_application(application, accepted=True)


def test_reject_application_records_reason() -> None:
    tenant = Tenant.objects.create(code="FIN-T5", name="Financing Tenant 5")
    with use_tenant(tenant.id):
        application = create_loan_application(
            tenant,
            type=FinLoanApplication.LOAN_TYPE_OPERATING,
            amount_requested_mga=Decimal("1000000"),
            duration_months=6,
        )
        submit_application(application)
        decide_application(application, accepted=False, rejection_reason="Garanties insuffisantes")
        application.refresh_from_db()
        assert application.state == FinLoanApplication.STATE_REJECTED
        assert application.rejection_reason == "Garanties insuffisantes"
