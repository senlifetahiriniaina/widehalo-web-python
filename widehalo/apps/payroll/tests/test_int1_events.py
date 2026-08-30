"""INT1 (chantier interactivite native inter-modules) : evenement
`payroll.period_validated`, publie par `services/periods.py::
validate_period` — absent jusqu'ici (verifie par lecture directe)."""

from __future__ import annotations

import pytest

from apps.core.models.event import EventLog
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.payroll.models import PayPeriod
from apps.payroll.services.periods import validate_period
from apps.payroll.tests.factories import make_period

pytestmark = pytest.mark.django_db


def test_validate_period_publishes_period_validated() -> None:
    tenant = Tenant.objects.create(code="PAY-INT1-PER", name="Payroll INT1 Period Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="pay-int1-per@example.com", password="Str0ngPassw0rd!23"
        )
        period = make_period(tenant)
        # Raccourci de test (meme discipline que `test_batches.
        # test_batch_validation_posts_balanced_accounting_entry`) : place
        # directement la periode en "verifiee", seule la publication de
        # l'evenement de `validate_period` est ici sous test.
        period.state = PayPeriod.STATE_VERIFIED
        period.save(update_fields=["state"])

        validate_period(period, user)

    event = EventLog.objects.get(event_type="payroll.period_validated", tenant_id=str(tenant.id))
    assert event.payload["period_id"] == str(period.id)
    assert event.payload["code"] == period.code
