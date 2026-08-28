"""Workflow §5.10.7 (FSM periode) + enrichissement "Workflow d'approbation
des bulletins" (etat `verifiee` formalise en circuit d'approbation
explicite, §5.10.11)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.payroll.models import PayPeriod
from apps.payroll.services.approvals import decide_period_verification, request_period_verification
from apps.payroll.services.periods import compute_period, ensure_active_contract_for_recompute
from apps.payroll.tests.factories import (
    make_active_contract,
    make_period,
    setup_payroll_reference_data,
)

pytestmark = pytest.mark.django_db


def test_full_period_workflow_via_approval_circuit() -> None:
    tenant = Tenant.objects.create(code="PAY-WF", name="Workflow")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        rh_user = User.objects.create_user(email="rh-wf@example.com", password="Str0ngPassw0rd!23")
        grant_role(rh_user, "rh")
        direction_user = User.objects.create_user(
            email="direction-wf@example.com", password="Str0ngPassw0rd!23"
        )
        grant_role(direction_user, "direction")

        employee_id = uuid.uuid4()
        make_active_contract(tenant, employee_id=employee_id, wage_base=Decimal("900000"))
        period = make_period(tenant)

        payslips = compute_period(period, rh_user, employee_ids=[employee_id])
        assert len(payslips) == 1
        period.refresh_from_db()
        assert period.state == PayPeriod.STATE_COMPUTING

        approval = request_period_verification(period, rh_user)
        period.refresh_from_db()
        assert period.state == PayPeriod.STATE_COMPUTING  # inchange tant que non decide

        decide_period_verification(approval.id, direction_user, approved=True)
        period.refresh_from_db()
        assert period.state == PayPeriod.STATE_VERIFIED


def test_verification_rejected_keeps_period_in_computing() -> None:
    tenant = Tenant.objects.create(code="PAY-WF2", name="Workflow rejet")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        rh_user = User.objects.create_user(email="rh-wf2@example.com", password="Str0ngPassw0rd!23")
        grant_role(rh_user, "rh")
        direction_user = User.objects.create_user(
            email="direction-wf2@example.com", password="Str0ngPassw0rd!23"
        )
        grant_role(direction_user, "direction")

        employee_id = uuid.uuid4()
        make_active_contract(tenant, employee_id=employee_id, wage_base=Decimal("900000"))
        period = make_period(tenant, code="2026-04")
        compute_period(period, rh_user, employee_ids=[employee_id])
        approval = request_period_verification(period, rh_user)

        decide_period_verification(approval.id, direction_user, approved=False)
        period.refresh_from_db()
        assert period.state == PayPeriod.STATE_COMPUTING


def test_ensure_active_contract_for_recompute_blocks_validated_period() -> None:
    from django.core.exceptions import ValidationError

    tenant = Tenant.objects.create(code="PAY-WF3", name="RG-PAY-10")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        employee_id = uuid.uuid4()
        contract = make_active_contract(
            tenant, employee_id=employee_id, wage_base=Decimal("900000")
        )
        period = make_period(tenant, code="2026-05")
        period.state = PayPeriod.STATE_VALIDATED
        period.save(update_fields=["state"])

        with pytest.raises(ValidationError):
            ensure_active_contract_for_recompute(contract, period)
