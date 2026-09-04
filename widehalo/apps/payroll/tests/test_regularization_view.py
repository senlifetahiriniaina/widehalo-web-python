"""Bloc E, E7 (PAY-9) : écran de régularisation
(`apps.payroll.views.regularization_screen`) — point d'entrée HTML réel
de `create_regularization`."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.core.models.audit import AuditLog
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.payroll.models import PayPayslip, PayPeriod
from apps.payroll.services.payslip import compute_payslip
from apps.payroll.tests.factories import (
    employee_client,
    make_active_contract,
    make_period,
    setup_payroll_reference_data,
    staff_client,
)

pytestmark = pytest.mark.django_db


def _validated_original(tenant: Tenant) -> PayPayslip:
    setup_payroll_reference_data(tenant)
    contract = make_active_contract(tenant, employee_id=uuid.uuid4(), wage_base=Decimal("1200000"))
    period = make_period(tenant)
    payslip = PayPayslip.objects.create(
        tenant=tenant,
        employee_id=contract.employee_id,
        contract=contract,
        period=period,
        date_from=period.date_from,
        date_to=period.date_to,
    )
    compute_payslip(payslip)
    payslip.state = PayPayslip.STATE_APPROVED
    payslip.save(update_fields=["state"])
    period.state = PayPeriod.STATE_VALIDATED
    period.save(update_fields=["state"])
    return payslip


def _open_target_period(tenant: Tenant) -> PayPeriod:
    return make_period(
        tenant,
        code="2026-04",
        date_from=dt.date(2026, 4, 1),
        date_to=dt.date(2026, 4, 30),
        payment_date=dt.date(2026, 4, 30),
    )


def test_non_staff_role_gets_403() -> None:
    tenant = Tenant.objects.create(code="PAY-E7-V1", name="E7 view non staff")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        employee_id = uuid.uuid4()
        client = employee_client(tenant, employee_id)

    response = client.get("/payroll/regularisation/")
    assert response.status_code == 403


def test_screen_lists_only_eligible_originals_and_target_periods() -> None:
    tenant = Tenant.objects.create(code="PAY-E7-V2", name="E7 view picker")
    with use_tenant(tenant.id):
        original = _validated_original(tenant)
        target_period = _open_target_period(tenant)
        client, _user = staff_client(tenant)

    response = client.get("/payroll/regularisation/")
    content = response.content.decode()

    assert response.status_code == 200
    assert str(original.id) in content
    assert str(target_period.id) in content
    # La periode DEJA verrouillee de l'original ne doit jamais apparaitre
    # comme option cible (elle porte deja une ecriture comptable postee).
    assert f'value="{original.period_id}"' not in content


def test_post_creates_regularization_and_displays_result() -> None:
    tenant = Tenant.objects.create(code="PAY-E7-V3", name="E7 view create")
    with use_tenant(tenant.id):
        original = _validated_original(tenant)
        target_period = _open_target_period(tenant)
        payslips_before = PayPayslip.objects.count()
        # `staff_client` fait de VRAIS appels HTTP (login/mfa) qui passent
        # par `TenantMiddleware` et ecrasent le contextvar de ce bloc — le
        # placer en dernier, meme discipline que `test_rubric_simulation_
        # view.py` (jamais de code apres lui dans le meme `with`).
        client, user = staff_client(tenant)

    response = client.post(
        "/payroll/regularisation/",
        {
            "original_id": str(original.id),
            "target_period_id": str(target_period.id),
            "reason": "Absence corrigée après paie.",
        },
    )
    content = response.content.decode()

    assert response.status_code == 200
    assert "1033300" in content

    with use_tenant(tenant.id):
        assert PayPayslip.objects.count() == payslips_before + 1
        regularization = PayPayslip.objects.get(rectifies=original)
        assert regularization.period_id == target_period.id
        log = AuditLog.objects.get(
            tenant_id=tenant.id, action=AuditLog.ACTION_PII_ACCESS, object_id=str(regularization.id)
        )
        assert log.actor_id == user.id


def test_post_without_reason_shows_error_and_creates_nothing() -> None:
    tenant = Tenant.objects.create(code="PAY-E7-V4", name="E7 view error")
    with use_tenant(tenant.id):
        original = _validated_original(tenant)
        target_period = _open_target_period(tenant)
        payslips_before = PayPayslip.objects.count()
        client, _user = staff_client(tenant)

    response = client.post(
        "/payroll/regularisation/",
        {"original_id": str(original.id), "target_period_id": str(target_period.id), "reason": ""},
    )

    assert response.status_code == 200
    assert "motif" in response.content.decode().lower()

    with use_tenant(tenant.id):
        assert PayPayslip.objects.count() == payslips_before
