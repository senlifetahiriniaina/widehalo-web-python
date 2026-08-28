from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.core.services.approvals import decide, pending_for_user
from apps.core.tests.factories import TenantFactory, UserFactory
from apps.core.tests.utils import grant_role, use_tenant
from apps.presence.models import PrsAbsence, PrsAbsenceType
from apps.presence.services.absences import (
    accrue_annual_leave,
    cancel_absence,
    create_absence,
    create_absence_type,
    decide_absence,
    mark_unjustified_if_overdue,
    submit_absence,
)
from apps.presence.services.employees import create_employee

pytestmark = pytest.mark.django_db


def _setup(tenant):
    employee = create_employee(
        tenant, first_name="Rina", last_name="Rakoto", hire_date=dt.date(2026, 1, 1)
    )
    return employee


def test_create_absence_computes_days_count_with_half_days() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        employee = _setup(tenant)
        absence_type = create_absence_type(
            tenant, code="CP", name="Congé payé", category=PrsAbsenceType.CATEGORY_PAID_LEAVE
        )
        absence = create_absence(
            tenant,
            employee=employee,
            absence_type=absence_type,
            date_from=dt.date(2026, 3, 2),
            date_to=dt.date(2026, 3, 6),
            half_day_start=True,
        )
        assert absence.days_count == Decimal("4.5")


def test_single_level_approval_workflow_validates_and_deducts_balance() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        employee = _setup(tenant)
        rh = UserFactory(email="rh@example.com")
        grant_role(rh, "rh")
        absence_type = create_absence_type(
            tenant,
            code="PERM",
            name="Permission",
            category=PrsAbsenceType.CATEGORY_PERMISSION,
            approval_levels=1,
        )
        absence = create_absence(
            tenant,
            employee=employee,
            absence_type=absence_type,
            date_from=dt.date(2026, 3, 2),
            date_to=dt.date(2026, 3, 2),
        )
        submit_absence(absence, rh)
        assert absence.state == PrsAbsence.STATE_SUBMITTED

        pending = pending_for_user(rh).get()
        decided = decide(pending, rh, approved=True)
        result = decide_absence(absence, decided, rh, approved=True)
        assert result.state == PrsAbsence.STATE_VALIDATED

        balance = result.employee.balances.get(year=2026, type=absence_type)
        assert balance.taken_days == Decimal("1")
        assert balance.pending_days == Decimal("0")


def test_two_level_approval_requires_second_decision() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        employee = _setup(tenant)
        rh = UserFactory(email="rh2@example.com")
        grant_role(rh, "rh")
        direction = UserFactory(email="direction@example.com")
        grant_role(direction, "direction")
        absence_type = create_absence_type(
            tenant,
            code="CP2",
            name="Congé payé",
            category=PrsAbsenceType.CATEGORY_PAID_LEAVE,
            approval_levels=2,
        )
        absence = create_absence(
            tenant,
            employee=employee,
            absence_type=absence_type,
            date_from=dt.date(2026, 4, 1),
            date_to=dt.date(2026, 4, 2),
        )
        submit_absence(absence, rh)
        level1 = pending_for_user(rh).get()
        decided1 = decide(level1, rh, approved=True)
        absence = decide_absence(absence, decided1, rh, approved=True)
        assert absence.state == PrsAbsence.STATE_APPROVED_L1

        level2 = pending_for_user(direction).get()
        decided2 = decide(level2, direction, approved=True)
        absence = decide_absence(absence, decided2, direction, approved=True)
        assert absence.state == PrsAbsence.STATE_VALIDATED


def test_rejected_absence_releases_pending_balance() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        employee = _setup(tenant)
        rh = UserFactory(email="rh3@example.com")
        grant_role(rh, "rh")
        absence_type = create_absence_type(
            tenant, code="CP3", name="Congé payé", category=PrsAbsenceType.CATEGORY_PAID_LEAVE
        )
        absence = create_absence(
            tenant,
            employee=employee,
            absence_type=absence_type,
            date_from=dt.date(2026, 5, 1),
            date_to=dt.date(2026, 5, 1),
        )
        submit_absence(absence, rh)
        pending = pending_for_user(rh).get()
        decided = decide(pending, rh, approved=False)
        absence = decide_absence(absence, decided, rh, approved=False)
        assert absence.state == PrsAbsence.STATE_REJECTED
        balance = absence.employee.balances.get(year=2026, type=absence_type)
        assert balance.pending_days == Decimal("0")


def test_cancel_draft_and_submitted_absence() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        employee = _setup(tenant)
        rh = UserFactory(email="rh4@example.com")
        grant_role(rh, "rh")
        absence_type = create_absence_type(
            tenant, code="CP4", name="Congé payé", category=PrsAbsenceType.CATEGORY_PAID_LEAVE
        )
        absence = create_absence(
            tenant,
            employee=employee,
            absence_type=absence_type,
            date_from=dt.date(2026, 6, 1),
            date_to=dt.date(2026, 6, 1),
        )
        cancel_absence(absence, rh)
        assert absence.state == PrsAbsence.STATE_CANCELLED


def test_accrual_prorated_for_employee_hired_mid_year() -> None:
    """Test d'acceptance §5.9.8 n°3."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        employee = create_employee(
            tenant, first_name="Toky", last_name="Rasoa", hire_date=dt.date(2026, 7, 1)
        )
        absence_type = create_absence_type(
            tenant, code="CP5", name="Congé payé", category=PrsAbsenceType.CATEGORY_PAID_LEAVE
        )
        balance = accrue_annual_leave(tenant, employee, absence_type, year=2026)
        # Embauche le 1er juillet -> 6 mois travailles sur 2026 (juil-dec).
        assert balance.acquired_days == Decimal("15.00")

        full_year_employee = create_employee(
            tenant, first_name="Full", last_name="Year", hire_date=dt.date(2025, 1, 1)
        )
        full_balance = accrue_annual_leave(tenant, full_year_employee, absence_type, year=2026)
        assert full_balance.acquired_days == Decimal("30.00")


def test_mark_unjustified_if_overdue() -> None:
    """Test d'acceptance §5.9.8 n°2 : absence maladie sans justificatif
    sous 48h passe en `injustifie`."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        employee = _setup(tenant)
        sick_type = create_absence_type(
            tenant,
            code="MAL",
            name="Maladie",
            category=PrsAbsenceType.CATEGORY_SICK,
            requires_justification=True,
            justification_deadline_days=2,
        )
        unjustified_type = create_absence_type(
            tenant,
            code="INJ",
            name="Injustifié",
            category=PrsAbsenceType.CATEGORY_UNJUSTIFIED,
        )
        absence = create_absence(
            tenant,
            employee=employee,
            absence_type=sick_type,
            date_from=dt.date(2020, 1, 1),
            date_to=dt.date(2020, 1, 1),
        )
        changed = mark_unjustified_if_overdue(absence, unjustified_type=unjustified_type)
        assert changed is True
        absence.refresh_from_db()
        assert absence.type_id == unjustified_type.id


def test_mark_unjustified_skips_when_justification_provided() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        employee = _setup(tenant)
        sick_type = create_absence_type(
            tenant,
            code="MAL2",
            name="Maladie",
            category=PrsAbsenceType.CATEGORY_SICK,
            requires_justification=True,
        )
        absence = create_absence(
            tenant,
            employee=employee,
            absence_type=sick_type,
            date_from=dt.date(2020, 1, 1),
            date_to=dt.date(2020, 1, 1),
        )
        absence.justification_provided = True
        absence.save(update_fields=["justification_provided"])
        changed = mark_unjustified_if_overdue(absence, unjustified_type=sick_type)
        assert changed is False
