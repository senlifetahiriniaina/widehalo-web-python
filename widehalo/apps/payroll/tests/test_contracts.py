"""Bloc E, E5 (PAY-6) : `apps.payroll.services.contracts.create_amendment`
— avenant = contrat ENFANT (`parent_contract`), l'original n'est jamais
modifié en place. Aucun test n'existait avant ce sprint (l'audit
constatait : « fonction de création jamais appelée en pratique »)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.payroll.models import PayContract
from apps.payroll.services.contracts import create_amendment
from apps.payroll.tests.factories import make_active_contract, setup_payroll_reference_data

pytestmark = pytest.mark.django_db


def test_create_amendment_creates_a_child_contract_and_preserves_the_original() -> None:
    tenant = Tenant.objects.create(code="PAY-E5-1", name="E5 amendment child")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        original = make_active_contract(
            tenant, employee_id=uuid.uuid4(), wage_base=Decimal("1200000")
        )
        original_wage_base = original.wage_base

        amendment = create_amendment(
            original, date_start=dt.date(2026, 6, 1), wage_base=Decimal("1400000")
        )

        assert amendment.id != original.id
        assert amendment.parent_contract_id == original.id
        assert amendment.employee_id == original.employee_id
        assert amendment.wage_base == Decimal("1400000")
        assert amendment.date_start == dt.date(2026, 6, 1)

        original.refresh_from_db()
        assert original.wage_base == original_wage_base
        assert original.parent_contract_id is None


def test_create_amendment_inherits_unoverridden_fields_from_the_original() -> None:
    tenant = Tenant.objects.create(code="PAY-E5-2", name="E5 amendment inherit")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        original = make_active_contract(
            tenant, employee_id=uuid.uuid4(), wage_base=Decimal("1200000")
        )

        amendment = create_amendment(original, date_start=dt.date(2026, 6, 1))

        assert amendment.wage_base == original.wage_base
        assert amendment.type_id == original.type_id
        assert amendment.salary_structure_id == original.salary_structure_id
        assert amendment.notice_days == original.notice_days


def test_create_amendment_only_overrides_explicitly_passed_fields() -> None:
    tenant = Tenant.objects.create(code="PAY-E5-3", name="E5 amendment overrides")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        original = make_active_contract(
            tenant, employee_id=uuid.uuid4(), wage_base=Decimal("1200000")
        )

        amendment = create_amendment(
            original, date_start=dt.date(2026, 6, 1), job_title="Chef d'équipe"
        )

        assert amendment.job_title == "Chef d'équipe"
        assert amendment.wage_base == original.wage_base


def test_original_contract_still_resolvable_as_a_distinct_row() -> None:
    """RG-PAY-6 : l'avenant n'efface jamais l'original — les deux
    coexistent en base, chacun sa propre ligne, l'original conservant
    son historique tel quel."""
    tenant = Tenant.objects.create(code="PAY-E5-4", name="E5 amendment coexist")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        original = make_active_contract(
            tenant, employee_id=uuid.uuid4(), wage_base=Decimal("1200000")
        )
        count_before = PayContract.objects.filter(tenant=tenant).count()

        create_amendment(original, date_start=dt.date(2026, 6, 1), wage_base=Decimal("1500000"))

        assert PayContract.objects.filter(tenant=tenant).count() == count_before + 1
        assert PayContract.objects.filter(tenant=tenant, id=original.id).exists()
