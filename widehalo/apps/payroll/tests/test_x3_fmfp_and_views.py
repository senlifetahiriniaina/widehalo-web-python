"""X3 refonte UX (Sprint 8 / L5, cf. docs/planning/2026-refonte-ux-sprints.md
§5) : FMFP (jusque-là absent), écran de détail du bulletin, téléchargement
PDF (corrige un lien mort). Même idiome que test_payslip_acceptance.py."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.payroll.models import PayPayslip
from apps.payroll.services.payslip import compute_payslip
from apps.payroll.tests.factories import (
    make_active_contract,
    make_period,
    setup_payroll_reference_data,
)
from apps.presence.tests.factories import PrsEmployeeFactory

pytestmark = pytest.mark.django_db


def _new_payslip(tenant: Tenant, contract, period) -> PayPayslip:
    return PayPayslip.objects.create(
        tenant=tenant,
        employee_id=contract.employee_id,
        contract=contract,
        period=period,
        date_from=period.date_from,
        date_to=period.date_to,
    )


def test_fmfp_pat_is_1_percent_of_base_cotisable_and_included_in_social_employer() -> None:
    tenant = Tenant.objects.create(code="PAY-FMFP", name="FMFP Tenant")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        contract = make_active_contract(
            tenant, employee_id=uuid.uuid4(), wage_base=Decimal("1200000")
        )
        period = make_period(tenant)
        payslip = _new_payslip(tenant, contract, period)
        compute_payslip(payslip)

        fmfp_line = payslip.lines.get(code="FMFP_PAT")
        assert fmfp_line.amount == Decimal("12000")  # 1 200 000 * 1%
        assert fmfp_line.is_employer_charge is True
        # CNAPS_PAT (13%) + OSTIE_PAT (5%) + FMFP_PAT (1%) = 19% de 1 200 000
        assert payslip.social_employer == Decimal("228000")


def _employee_client(tenant: Tenant, employee_id) -> Client:
    user = User.objects.create_user(
        email=f"emp-{employee_id}@example.com", password="Str0ngPassw0rd!23"
    )
    PrsEmployeeFactory(tenant=tenant, id=employee_id, user=user)
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def test_payslip_detail_visible_to_own_employee() -> None:
    tenant = Tenant.objects.create(code="PAY-DET-1", name="Payslip Detail Tenant 1")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        employee_id = uuid.uuid4()
        contract = make_active_contract(
            tenant, employee_id=employee_id, wage_base=Decimal("1200000")
        )
        period = make_period(tenant)
        payslip = _new_payslip(tenant, contract, period)
        compute_payslip(payslip)
        client = _employee_client(tenant, employee_id)

    response = client.get(f"/payroll/{payslip.id}/")
    assert response.status_code == 200
    assert b"FMFP" in response.content


def test_payslip_detail_forbidden_for_another_employee() -> None:
    tenant = Tenant.objects.create(code="PAY-DET-2", name="Payslip Detail Tenant 2")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        owner_id = uuid.uuid4()
        contract = make_active_contract(tenant, employee_id=owner_id, wage_base=Decimal("1200000"))
        period = make_period(tenant)
        payslip = _new_payslip(tenant, contract, period)
        compute_payslip(payslip)
        other_client = _employee_client(tenant, uuid.uuid4())

    response = other_client.get(f"/payroll/{payslip.id}/")
    assert response.status_code == 403


def test_payslip_download_returns_a_pdf() -> None:
    tenant = Tenant.objects.create(code="PAY-PDF", name="Payslip PDF Tenant")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        employee_id = uuid.uuid4()
        contract = make_active_contract(
            tenant, employee_id=employee_id, wage_base=Decimal("1200000")
        )
        period = make_period(tenant)
        payslip = _new_payslip(tenant, contract, period)
        compute_payslip(payslip)
        client = _employee_client(tenant, employee_id)

    response = client.get(f"/payroll/{payslip.id}/pdf/")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"


def test_my_payslips_no_longer_links_to_itself() -> None:
    tenant = Tenant.objects.create(code="PAY-LINK", name="Payslip Link Tenant")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        employee_id = uuid.uuid4()
        contract = make_active_contract(
            tenant, employee_id=employee_id, wage_base=Decimal("1200000")
        )
        period = make_period(tenant)
        payslip = _new_payslip(tenant, contract, period)
        compute_payslip(payslip)
        client = _employee_client(tenant, employee_id)

    body = client.get("/payroll/").content.decode()
    assert f"/payroll/{payslip.id}/pdf/" in body
    assert f"/payroll/{payslip.id}/" in body
