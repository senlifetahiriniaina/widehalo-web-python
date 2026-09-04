"""Bloc E, E3 (PAY-4) : « chaque ligne référence la version exacte du
`RegulatoryParameter` appliqué » — `PayrollParams.versions` (resolu par
`apps.payroll.services.params.resolve_params`) et son report sur
`PayPayslipLine.regulatory_parameter_versions` (meme instantane sur
chaque ligne d'un meme bulletin, cf. docstring du champ)."""

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
from apps.payroll.services.seed import CODE_CNAPS_RATE, CODE_IRSA_BRACKETS
from apps.payroll.tests.factories import (
    make_active_contract,
    make_period,
    setup_payroll_reference_data,
)

pytestmark = pytest.mark.django_db


def test_resolve_params_versions_start_at_one_for_a_freshly_seeded_tenant() -> None:
    tenant = Tenant.objects.create(code="PAY-E3-1", name="E3 versions v1")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        params = resolve_params(tenant, dt.date(2026, 3, 1))
        assert params.versions[CODE_CNAPS_RATE] == 1
        assert params.versions[CODE_IRSA_BRACKETS] == 1
        # Tous les codes seedes ont une version resolue — aucun trou.
        assert len(params.versions) == 10


def test_resolve_params_versions_bump_independently_per_code() -> None:
    """Une nouvelle version d'UN SEUL parametre ne fait bouger QUE sa
    propre entree dans `versions` — les autres lignees restent a leur
    version courante, chaque code ayant sa propre lignee independante."""
    tenant = Tenant.objects.create(code="PAY-E3-2", name="E3 versions bump")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        RegulatoryParameter.objects.filter(tenant=tenant, code=CODE_CNAPS_RATE).update(
            valid_to=dt.date(2026, 5, 31)
        )
        RegulatoryParameter.objects.create(
            tenant=tenant,
            code=CODE_CNAPS_RATE,
            value={"employer": "0.14", "employee": "0.01"},
            valid_from=dt.date(2026, 6, 1),
            valid_to=None,
        )

        params_before = resolve_params(tenant, dt.date(2026, 3, 1))
        params_after = resolve_params(tenant, dt.date(2026, 6, 15))

        assert params_before.versions[CODE_CNAPS_RATE] == 1
        assert params_after.versions[CODE_CNAPS_RATE] == 2
        # Un autre code, jamais retouche, reste a la version 1 des deux cotes.
        assert params_before.versions[CODE_IRSA_BRACKETS] == 1
        assert params_after.versions[CODE_IRSA_BRACKETS] == 1


def test_payslip_lines_carry_the_resolved_parameter_version_snapshot() -> None:
    tenant = Tenant.objects.create(code="PAY-E3-3", name="E3 lines snapshot")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        employee_id = uuid.uuid4()
        contract = make_active_contract(
            tenant, employee_id=employee_id, wage_base=Decimal("1200000")
        )
        period = make_period(tenant)
        payslip = PayPayslip.objects.create(
            tenant=tenant,
            employee_id=employee_id,
            contract=contract,
            period=period,
            date_from=period.date_from,
            date_to=period.date_to,
        )
        compute_payslip(payslip)

        expected_versions = resolve_params(tenant, period.date_from).versions
        lines = list(payslip.lines.all())
        assert lines, "le calcul doit produire au moins une ligne"
        for line in lines:
            assert line.regulatory_parameter_versions == expected_versions


def test_payslip_lines_snapshot_reflects_a_bumped_version_on_recompute() -> None:
    """Un recalcul APRES une nouvelle version d'un parametre (mais toujours
    a la meme date de periode, PAY-M3) reproduit la MEME resolution — donc
    le MEME instantane de versions — puisque seule la date de periode
    pilote la resolution, jamais la date du recalcul."""
    tenant = Tenant.objects.create(code="PAY-E3-4", name="E3 lines recompute")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        employee_id = uuid.uuid4()
        contract = make_active_contract(
            tenant, employee_id=employee_id, wage_base=Decimal("1200000")
        )
        period = make_period(
            tenant, code="2026-03", date_from=dt.date(2026, 3, 1), date_to=dt.date(2026, 3, 31)
        )
        payslip = PayPayslip.objects.create(
            tenant=tenant,
            employee_id=employee_id,
            contract=contract,
            period=period,
            date_from=period.date_from,
            date_to=period.date_to,
        )
        compute_payslip(payslip)
        first_versions = {
            line.code: line.regulatory_parameter_versions for line in payslip.lines.all()
        }

        # Nouvelle version de CNAPS, effective a partir de juin 2026 —
        # n'affecte pas une periode de mars deja calculee ni un recalcul
        # ulterieur de cette meme periode.
        RegulatoryParameter.objects.filter(tenant=tenant, code=CODE_CNAPS_RATE).update(
            valid_to=dt.date(2026, 5, 31)
        )
        RegulatoryParameter.objects.create(
            tenant=tenant,
            code=CODE_CNAPS_RATE,
            value={"employer": "0.14", "employee": "0.01"},
            valid_from=dt.date(2026, 6, 1),
            valid_to=None,
        )

        compute_payslip(payslip)
        second_versions = {
            line.code: line.regulatory_parameter_versions for line in payslip.lines.all()
        }

        assert first_versions == second_versions
        assert any(v[CODE_CNAPS_RATE] == 1 for v in second_versions.values())
