"""Tests du contrat public de `payroll` (`apps/payroll/services/public.py`)
— seule surface qu'un autre module (ex. `strategy`, rapport business plan)
a le droit d'importer. Couvre le gap ajoute pendant le chantier `strategy` :
`get_payroll_mass_projection` (PAY-PROJ1)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.payroll.services.public import get_payroll_mass_projection
from apps.payroll.tests.factories import make_active_contract, setup_payroll_reference_data

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
