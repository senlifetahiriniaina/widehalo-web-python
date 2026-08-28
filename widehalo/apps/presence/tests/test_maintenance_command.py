from __future__ import annotations

import datetime as dt
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.core.tests.factories import TenantFactory, UserFactory
from apps.core.tests.utils import grant_role, use_tenant
from apps.presence.models import PrsAbsence
from apps.presence.services.absences import create_absence, create_absence_type
from apps.presence.services.attendance import check_in
from apps.presence.services.employees import create_employee

pytestmark = pytest.mark.django_db


def test_run_presence_maintenance_purges_and_marks_unjustified() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        rh = UserFactory(email="rh-maint@example.com")
        grant_role(rh, "rh")
        employee = create_employee(
            tenant, first_name="Rina", last_name="Rakoto", hire_date=dt.date(2020, 1, 1)
        )

        attendance = check_in(
            employee,
            mode="mobile",
            latitude=Decimal("-18.879"),
            longitude=Decimal("47.507"),
            site_latitude=Decimal("-18.879"),
            site_longitude=Decimal("47.507"),
            radius_meters=200,
        )
        attendance.geo_captured_at = timezone.now() - dt.timedelta(days=45)
        attendance.save(update_fields=["geo_captured_at"])

        create_absence_type(tenant, code="INJ-CMD", name="Injustifié", category="injustifie")
        sick_type = create_absence_type(
            tenant,
            code="MAL-CMD",
            name="Maladie",
            category="maladie",
            requires_justification=True,
            justification_deadline_days=2,
        )
        sick_absence = create_absence(
            tenant,
            employee=employee,
            absence_type=sick_type,
            date_from=dt.date(2020, 1, 1),
            date_to=dt.date(2020, 1, 1),
        )
        # Etat force directement (pas de transition) pour isoler ce test
        # de maintenance du workflow d'approbation complet, deja teste par
        # ailleurs (`test_absences.py`) — meme discipline que
        # `MrpCraFactory` (etat FSM assigne, jamais une methode `@transition`
        # appelee depuis une factory/un test de mise en place).
        sick_absence.state = PrsAbsence.STATE_VALIDATED
        sick_absence.save(update_fields=["state"])

    out = StringIO()
    call_command("run_presence_maintenance", stdout=out)
    output = out.getvalue()
    assert "purgee" in output
    assert "1 absence(s) basculee(s)" in output

    attendance.refresh_from_db()
    assert attendance.latitude is None
