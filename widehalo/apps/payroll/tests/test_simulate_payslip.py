"""Bloc E, E4 (PAY-5) : `apps.payroll.services.payslip.simulate_payslip`
— coeur purement fonctionnel extrait de `compute_payslip` (meme moteur,
aucune ecriture en base) — reutilise par l'ecran de simulation sur
salarié témoin (`apps.payroll.views.rubric_simulation`). Preuve directe
de non-regression du refactor : `simulate_payslip` doit produire
EXACTEMENT les memes montants que `compute_payslip` pour les memes
entrées."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.payroll.models import PayPayslip, PayPayslipLine
from apps.payroll.services.payslip import compute_payslip, simulate_payslip
from apps.payroll.tests.factories import (
    make_active_contract,
    make_period,
    setup_payroll_reference_data,
)

pytestmark = pytest.mark.django_db


def test_simulate_payslip_never_writes_to_the_database() -> None:
    tenant = Tenant.objects.create(code="PAY-E4-1", name="E4 simulate no persist")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        employee_id = uuid.uuid4()
        contract = make_active_contract(
            tenant, employee_id=employee_id, wage_base=Decimal("1200000")
        )
        period = make_period(tenant)

        payslips_before = PayPayslip.objects.count()
        lines_before = PayPayslipLine.objects.count()

        simulate_payslip(
            tenant,
            contract,
            employee_id=employee_id,
            date_from=period.date_from,
            date_to=period.date_to,
        )

        assert PayPayslip.objects.count() == payslips_before
        assert PayPayslipLine.objects.count() == lines_before


def test_simulate_payslip_matches_compute_payslip_exactly() -> None:
    """Meme entree (salarie temoin), meme resultat que la chaine reelle
    (`compute_payslip`, qui persiste) — la preuve que le refactor n'a
    introduit aucune divergence de comportement entre les deux chemins."""
    tenant = Tenant.objects.create(code="PAY-E4-2", name="E4 simulate matches real")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        employee_id = uuid.uuid4()
        contract = make_active_contract(
            tenant, employee_id=employee_id, wage_base=Decimal("1200000")
        )
        period = make_period(tenant)

        simulation = simulate_payslip(
            tenant,
            contract,
            employee_id=employee_id,
            date_from=period.date_from,
            date_to=period.date_to,
        )
        simulated_by_code = {r.rule.code: r.amount for r in simulation.results}

        payslip = PayPayslip.objects.create(
            tenant=tenant,
            employee_id=employee_id,
            contract=contract,
            period=period,
            date_from=period.date_from,
            date_to=period.date_to,
        )
        compute_payslip(payslip)
        real_by_code = {line.code: line.amount for line in payslip.lines.all()}

        assert simulated_by_code == real_by_code
        # Hand-check identique au test d'acceptance n°1 (meme wage_base).
        assert simulated_by_code["NET_A_PAYER"] == Decimal("1033300")


def test_simulate_payslip_resolves_params_at_date_from_never_today() -> None:
    """PAY-M3, applique a la simulation : la date choisie par l'utilisateur
    (`date_from`) pilote seule la resolution des parametres, jamais
    `date.today()`."""
    tenant = Tenant.objects.create(code="PAY-E4-3", name="E4 simulate PAY-M3")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        employee_id = uuid.uuid4()
        contract = make_active_contract(
            tenant, employee_id=employee_id, wage_base=Decimal("1200000")
        )

        simulation = simulate_payslip(
            tenant,
            contract,
            employee_id=employee_id,
            date_from=dt.date(2026, 3, 1),
            date_to=dt.date(2026, 3, 31),
        )
        assert simulation.payroll_params.at_date == dt.date(2026, 3, 1)
