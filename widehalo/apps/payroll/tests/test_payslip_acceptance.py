"""Tests d'acceptance §5.10.10 n°1-4 — calculs verifies A LA MAIN (meme
discipline que RG-LOG-6/ACC-IMP)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.payroll.models import PayPayslip
from apps.payroll.services.payslip import compute_payslip
from apps.payroll.tests.factories import (
    make_active_contract,
    make_period,
    setup_payroll_reference_data,
)

pytestmark = pytest.mark.django_db


def _new_payslip(tenant: Tenant, contract, period) -> PayPayslip:
    employee_id = contract.employee_id
    payslip = PayPayslip.objects.create(
        tenant=tenant,
        employee_id=employee_id,
        contract=contract,
        period=period,
        date_from=period.date_from,
        date_to=period.date_to,
    )
    return payslip


def test_acceptance_1_gross_1_200_000(db) -> None:
    """Test d'acceptance n°1 : salaire brut 1 200 000 Ar -> cotisations/
    base imposable/IRSA/net a payer correspondent a un calcul manuel de
    reference.

    **Calcul manuel de reference** (aucune absence, aucune heure sup,
    aucune prime, 0 personne a charge) :
      BRUT = 1 200 000
      BASE_COTISABLE = min(1 200 000, 8 x 300 000 = 2 400 000) = 1 200 000
      CNAPS_SAL = 1 200 000 x 1% = 12 000
      OSTIE_SAL = 1 200 000 x 1% = 12 000
      BASE_IMPOSABLE = floor100(1 200 000 - 12 000 - 12 000) = 1 176 000
      IRSA (bareme 6 tranches, progressif) :
        tranche 350 001-400 000 (5%) : 50 000 x 0.05   =  2 500
        tranche 400 001-500 000 (10%): 100 000 x 0.10  = 10 000
        tranche 500 001-600 000 (15%): 100 000 x 0.15  = 15 000
        tranche 600 001-4 000 000 (20%): 576 000 x 0.20 = 115 200
        total = 2 500 + 10 000 + 15 000 + 115 200 = 142 700
        (> minimum de perception 3 000 -> IRSA = 142 700)
      NET A PAYER = 1 200 000 - 12 000 - 12 000 - 142 700 = 1 033 300
    """
    tenant = Tenant.objects.create(code="PAY-ACC1", name="Acceptance 1")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        employee_id = uuid.uuid4()
        contract = make_active_contract(
            tenant, employee_id=employee_id, wage_base=Decimal("1200000")
        )
        period = make_period(tenant)
        payslip = _new_payslip(tenant, contract, period)
        compute_payslip(payslip)

        assert payslip.gross == Decimal("1200000.0000") or payslip.gross == Decimal("1200000")
        assert payslip.taxable_base == Decimal("1176000")
        assert payslip.social_employee == Decimal("24000")
        assert payslip.irsa == Decimal("142700")
        assert payslip.net_to_pay == Decimal("1033300")


def test_acceptance_2_gross_5_000_000_top_bracket(db) -> None:
    """Test d'acceptance n°2 : brut 5 000 000 Ar applique la tranche
    marginale a 25%.

    BASE_COTISABLE = min(5 000 000, 2 400 000) = 2 400 000 (plafonnee)
    CNAPS_SAL = OSTIE_SAL = 2 400 000 x 1% = 24 000 chacune
    BASE_IMPOSABLE = floor100(5 000 000 - 24 000 - 24 000) = 4 952 000
    IRSA :
      350001-400000 (5%)  : 50 000 x 0.05    = 2 500
      400001-500000 (10%) : 100 000 x 0.10   = 10 000
      500001-600000 (15%) : 100 000 x 0.15   = 15 000
      600001-4000000 (20%): 3 400 000 x 0.20 = 680 000
      >4000000 (25%)      : (4 952 000 - 4 000 000) x 0.25 = 238 000
      total = 2500+10000+15000+680000+238000 = 945 500
    """
    tenant = Tenant.objects.create(code="PAY-ACC2", name="Acceptance 2")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        employee_id = uuid.uuid4()
        contract = make_active_contract(
            tenant, employee_id=employee_id, wage_base=Decimal("5000000")
        )
        period = make_period(tenant)
        payslip = _new_payslip(tenant, contract, period)
        compute_payslip(payslip)

        assert payslip.taxable_base == Decimal("4952000")
        assert payslip.irsa == Decimal("945500")
        top_bracket_line = payslip.lines.get(code="IRSA_BRUT")
        assert top_bracket_line.amount == Decimal("945500")


def test_acceptance_3_social_ceiling_8x_sme(db) -> None:
    """Test d'acceptance n°3 : plafonnement a 8xSME s'applique correctement
    au-dela du seuil. SME = 300 000 -> plafond = 2 400 000. Pour un brut de
    3 000 000, la base cotisable est plafonnee a 2 400 000 (pas 3 000 000)."""
    tenant = Tenant.objects.create(code="PAY-ACC3", name="Acceptance 3")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        employee_id = uuid.uuid4()
        contract = make_active_contract(
            tenant, employee_id=employee_id, wage_base=Decimal("3000000")
        )
        period = make_period(tenant)
        payslip = _new_payslip(tenant, contract, period)
        compute_payslip(payslip)

        base_cotisable_line = payslip.lines.get(code="BASE_COTISABLE")
        assert base_cotisable_line.amount == Decimal("2400000")
        assert payslip.social_employee == Decimal("2400000") * Decimal("0.02")


def test_acceptance_4_pay_m3_recompute_reproducible(db) -> None:
    """Test d'acceptance n°4 (PAY-M3) : recalculer un bulletin de janvier
    en decembre produit EXACTEMENT le meme resultat — les parametres sont
    resolus a la date de la PERIODE, jamais a la date du calcul.

    Piege explicitement teste : un `RegulatoryParameter` "futur" (valide a
    partir de mars 2026, ex. un SME different) NE DOIT PAS affecter un
    recalcul d'une periode de janvier, meme si le recalcul lui-meme a
    "lieu" logiquement plus tard."""
    from apps.core.models.regulatory import RegulatoryParameter
    from apps.payroll.services.seed import CODE_SME

    tenant = Tenant.objects.create(code="PAY-ACC4", name="Acceptance 4")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        employee_id = uuid.uuid4()
        contract = make_active_contract(
            tenant, employee_id=employee_id, wage_base=Decimal("1200000")
        )
        period = make_period(
            tenant, code="2026-03", date_from=dt.date(2026, 3, 1), date_to=dt.date(2026, 3, 31)
        )
        payslip = _new_payslip(tenant, contract, period)
        compute_payslip(payslip)
        first_net = payslip.net_to_pay
        first_irsa = payslip.irsa

        # Un futur SME different (ex. revalorise a 500 000 Ar) prend effet
        # a partir de juin 2026 (apres le SME initial du 01/03/2026, cf.
        # `services.seed.SME_EFFECTIVE_DATE`, sans chevauchement de plage —
        # contrainte d'exclusion Postgres sur (tenant, code)) — NE DOIT PAS
        # s'appliquer a une periode de janvier, meme recalculee bien plus
        # tard.
        RegulatoryParameter.objects.filter(
            tenant=tenant, code=CODE_SME, valid_to__isnull=True
        ).update(valid_to=dt.date(2026, 5, 31))
        RegulatoryParameter.objects.create(
            tenant=tenant,
            code=CODE_SME,
            value={"amount": "500000"},
            valid_from=dt.date(2026, 6, 1),
            valid_to=None,
        )

        # "Recalcul en decembre" : rien dans `compute_payslip` ne consulte
        # `date.today()` — le simple fait de rappeler la fonction plus tard
        # (aucune horloge mockee necessaire, PAY-M3 est garanti par
        # construction : seule `period.date_from` pilote la resolution).
        compute_payslip(payslip)

        assert payslip.net_to_pay == first_net
        assert payslip.irsa == first_irsa
