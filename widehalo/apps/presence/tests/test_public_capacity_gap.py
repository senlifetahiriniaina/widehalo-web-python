"""Test du gap ajoute pour CAP1-2 (cf. plan, chantier « capacite de charge
a 90 jours ») : `get_tenant_absence_days_in_period`, seul gap de
`presence.services.public` NOUVEAU pour ce chantier (les autres gaps
utilises par `strategy.services.capacity_review` existaient deja)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.core.tests.utils import use_tenant
from apps.presence.models import PrsAbsence
from apps.presence.services.public import get_tenant_absence_days_in_period
from apps.presence.tests.factories import PrsAbsenceFactory, PrsEmployeeFactory

pytestmark = pytest.mark.django_db


def test_aggregates_validated_absences_across_employees_clipped_to_window() -> None:
    from apps.core.tests.factories import TenantFactory

    tenant = TenantFactory()
    with use_tenant(tenant.id):
        employee_a = PrsEmployeeFactory(tenant=tenant)
        employee_b = PrsEmployeeFactory(tenant=tenant)
        # Entierement dans la fenetre : 3 jours-personne.
        PrsAbsenceFactory(
            tenant=tenant,
            employee=employee_a,
            date_from=dt.date(2026, 3, 2),
            date_to=dt.date(2026, 3, 4),
            days_count=3,
            state=PrsAbsence.STATE_VALIDATED,
        )
        # Deborde la fenetre : clippee a [1er mars, 31 mars] -> 2 jours.
        PrsAbsenceFactory(
            tenant=tenant,
            employee=employee_b,
            date_from=dt.date(2026, 3, 30),
            date_to=dt.date(2026, 4, 2),
            days_count=4,
            state=PrsAbsence.STATE_VALIDATED,
        )
        # Hors fenetre : ignoree.
        PrsAbsenceFactory(
            tenant=tenant,
            employee=employee_a,
            date_from=dt.date(2026, 5, 1),
            date_to=dt.date(2026, 5, 2),
            days_count=2,
            state=PrsAbsence.STATE_VALIDATED,
        )
        # Brouillon : jamais comptee.
        PrsAbsenceFactory(
            tenant=tenant,
            employee=employee_a,
            date_from=dt.date(2026, 3, 10),
            date_to=dt.date(2026, 3, 10),
            days_count=1,
            state=PrsAbsence.STATE_DRAFT,
        )

        total = get_tenant_absence_days_in_period(
            tenant, date_from=dt.date(2026, 3, 1), date_to=dt.date(2026, 3, 31)
        )

        assert total == Decimal(5)


def test_returns_zero_without_any_absence() -> None:
    from apps.core.tests.factories import TenantFactory

    tenant = TenantFactory()
    with use_tenant(tenant.id):
        assert get_tenant_absence_days_in_period(
            tenant, date_from=dt.date(2026, 1, 1), date_to=dt.date(2026, 1, 31)
        ) == Decimal(0)
