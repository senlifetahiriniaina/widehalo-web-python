"""Bloc E, E1 (PAY-1) : les majorations d'heures supplementaires sont
resolues depuis le `RegulatoryParameter` versionne `payroll.
overtime_multipliers` (`apps.payroll.services.params.resolve_params`),
plus jamais depuis un dict Python en dur dans `apps.payroll.services.expr`
— verifie ici de bout en bout via `compute_payslip`, pas seulement au
niveau de la fonction de formule (deja couvert par `test_expr.py`)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.core.models.regulatory import RegulatoryParameter
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.payroll.models import PayPayslip
from apps.payroll.services.params import resolve_params
from apps.payroll.services.payslip import compute_payslip
from apps.payroll.services.seed import CODE_OVERTIME_MULTIPLIERS
from apps.payroll.tests.factories import (
    make_active_contract,
    make_period,
    setup_payroll_reference_data,
)

pytestmark = pytest.mark.django_db


def _new_payslip(tenant: Tenant, contract, period, *, overtime_hours: dict) -> PayPayslip:
    return PayPayslip.objects.create(
        tenant=tenant,
        employee_id=contract.employee_id,
        contract=contract,
        period=period,
        date_from=period.date_from,
        date_to=period.date_to,
        overtime_hours=overtime_hours,
    )


def test_resolve_params_reads_overtime_multipliers_from_regulatory_parameter() -> None:
    tenant = Tenant.objects.create(code="PAY-E1-1", name="E1 resolve_params")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        params = resolve_params(tenant, dt.date(2026, 3, 1))
        assert params.overtime_multipliers == {
            "h_sup_30": Decimal("1.30"),
            "h_sup_50": Decimal("1.50"),
            "nuit": Decimal("1.30"),
            "dimanche": Decimal("1.40"),
            "ferie": Decimal("2.00"),
        }


def test_heures_sup_line_reflects_seeded_multiplier() -> None:
    """Salaire de base 1 040 000 Ar (26 jours x 8h) -> taux horaire = 5 000
    Ar exact. 10h de categorie h_sup_50 (multiplicateur seede 1.50) ->
    HEURES_SUP = 10 x 5 000 x 1.50 = 75 000 Ar."""
    tenant = Tenant.objects.create(code="PAY-E1-2", name="E1 HEURES_SUP")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        employee_id = uuid.uuid4()
        contract = make_active_contract(
            tenant, employee_id=employee_id, wage_base=Decimal("1040000")
        )
        period = make_period(tenant)
        payslip = _new_payslip(tenant, contract, period, overtime_hours={"h_sup_50": "10"})
        compute_payslip(payslip)

        heures_sup_line = payslip.lines.get(code="HEURES_SUP")
        assert heures_sup_line.amount == Decimal("75000")


def test_heures_sup_line_reflects_a_tenant_specific_multiplier_override() -> None:
    """Preuve que le calcul lit reellement le `RegulatoryParameter`, pas un
    defaut fige ailleurs dans le code : un multiplicateur different pour
    la meme categorie change le montant du bulletin, sans toucher a
    `apps.payroll.services.expr`."""
    tenant = Tenant.objects.create(code="PAY-E1-3", name="E1 override")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        RegulatoryParameter.objects.filter(tenant=tenant, code=CODE_OVERTIME_MULTIPLIERS).update(
            value={
                "h_sup_30": "1.30",
                "h_sup_50": "2.00",
                "nuit": "1.30",
                "dimanche": "1.40",
                "ferie": "2.00",
            }
        )
        employee_id = uuid.uuid4()
        contract = make_active_contract(
            tenant, employee_id=employee_id, wage_base=Decimal("1040000")
        )
        period = make_period(tenant)
        payslip = _new_payslip(tenant, contract, period, overtime_hours={"h_sup_50": "10"})
        compute_payslip(payslip)

        heures_sup_line = payslip.lines.get(code="HEURES_SUP")
        # 10 x 5 000 x 2.00 = 100 000, distinct de la valeur par defaut
        # (75 000, cf. test_heures_sup_line_reflects_seeded_multiplier).
        assert heures_sup_line.amount == Decimal("100000")
