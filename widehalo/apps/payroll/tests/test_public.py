"""Tests du contrat public de `payroll` (`apps/payroll/services/public.py`)
— seule surface qu'un autre module (ex. `strategy`, rapport business plan)
a le droit d'importer. Couvre le gap ajoute pendant le chantier `strategy` :
`get_payroll_mass_projection` (PAY-PROJ1), et le gap ajoute pour le Bloc
Transverse T4 (FOR-11) : `list_published_payslips_for_warehouse`."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.payroll.models import PayPayslip
from apps.payroll.services.public import (
    get_payroll_mass_projection,
    list_published_payslips_for_warehouse,
)
from apps.payroll.tests.factories import (
    PayPayslipFactory,
    PayPayslipLineFactory,
    make_active_contract,
    setup_payroll_reference_data,
)

pytestmark = pytest.mark.django_db


def test_get_payroll_mass_projection_uses_active_contracts_only() -> None:
    tenant = Tenant.objects.create(code="PAY-PUB", name="Payroll Public Tenant")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        make_active_contract(tenant, employee_id=uuid.uuid4(), wage_base=Decimal("1000000"))

        rows = get_payroll_mass_projection(tenant, months=1)

        assert len(rows) == 1
        assert rows[0]["total_wage_base"] == Decimal("1000000")
        assert rows[0]["total_employer_social"] > Decimal(0)


def test_get_payroll_mass_projection_empty_without_contracts() -> None:
    tenant = Tenant.objects.create(code="PAY-PUB2", name="Payroll Public Tenant 2")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)

        rows = get_payroll_mass_projection(tenant, months=1)

        assert len(rows) == 1
        assert rows[0]["total_wage_base"] == Decimal(0)


def test_list_published_payslips_for_warehouse_includes_approved_and_paid() -> None:
    """Bloc Transverse, T4 : `state in (approved, paid)` — même
    définition exacte que le docstring "publié" de `PayPayslip`
    (Bloc E, E9/PAY-8)."""
    tenant = Tenant.objects.create(code="PAY-PUB-T4", name="Payroll Public T4 Tenant")
    with use_tenant(tenant.id):
        PayPayslipFactory(tenant=tenant, state=PayPayslip.STATE_APPROVED)
        PayPayslipFactory(tenant=tenant, state=PayPayslip.STATE_PAID)
        PayPayslipFactory(tenant=tenant, state=PayPayslip.STATE_TO_APPROVE)

        rows = list_published_payslips_for_warehouse(tenant)

        assert len(rows) == 2
        assert {row["state"] for row in rows} == {PayPayslip.STATE_APPROVED, PayPayslip.STATE_PAID}


def test_list_published_payslips_for_warehouse_never_exposes_net_to_pay() -> None:
    """RG-PAY-9/P5 ("cloisonnement paie transverse") : le montant net
    individuellement chiffré n'a jamais sa place dans ce dict — décision
    explicitement disclosée dans la docstring de la fonction."""
    tenant = Tenant.objects.create(code="PAY-PUB-T4-NET", name="Payroll Public T4 Net Tenant")
    with use_tenant(tenant.id):
        PayPayslipFactory(tenant=tenant, state=PayPayslip.STATE_APPROVED)

        rows = list_published_payslips_for_warehouse(tenant)

        assert len(rows) == 1
        assert "net_to_pay" not in rows[0]


def test_list_published_payslips_for_warehouse_carries_regulatory_parameter_versions() -> None:
    tenant = Tenant.objects.create(code="PAY-PUB-T4-VER", name="Payroll Public T4 Versions Tenant")
    with use_tenant(tenant.id):
        payslip = PayPayslipFactory(tenant=tenant, state=PayPayslip.STATE_APPROVED)
        PayPayslipLineFactory(
            tenant=tenant,
            payslip=payslip,
            regulatory_parameter_versions={"payroll.overtime_multipliers": 2},
        )

        rows = list_published_payslips_for_warehouse(tenant)

        assert rows[0]["regulatory_parameter_versions"] == {"payroll.overtime_multipliers": 2}


def test_list_published_payslips_for_warehouse_filters_by_updated_since() -> None:
    tenant = Tenant.objects.create(code="PAY-PUB-T4-UPD", name="Payroll Public T4 Updated Tenant")
    with use_tenant(tenant.id):
        PayPayslipFactory(tenant=tenant, state=PayPayslip.STATE_APPROVED)

        future = dt.datetime.now(dt.UTC) + dt.timedelta(days=1)
        assert list_published_payslips_for_warehouse(tenant, updated_since=future) == []
