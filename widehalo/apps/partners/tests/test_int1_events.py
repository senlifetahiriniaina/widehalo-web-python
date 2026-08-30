"""INT1 (chantier interactivite native inter-modules) : evenement
`partners.duplicate_alert_created` (`services/onboarding.py::create_partner`)
et action `partners.notify_role_of_duplicate` enregistree dans
`core.services.automation_registry`."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group

from apps.core.models.event import EventLog
from apps.core.models.notification import Notification
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.services.automation_registry import get_registered_action
from apps.core.tests.utils import use_tenant
from apps.partners.models import DuplicateAlert, Partner
from apps.partners.services.onboarding import create_partner

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return Tenant.objects.create(code="PART-INT1-T", name="Partners INT1 Tenant")


def test_duplicate_nif_publishes_duplicate_alert_created(tenant) -> None:
    with use_tenant(tenant.id):
        first = create_partner(
            tenant=tenant, name="Alpha", roles=[Partner.ROLE_SUPPLIER], nif="NIF-INT1-001"
        )
        second = create_partner(
            tenant=tenant, name="Alpha Bis", roles=[Partner.ROLE_SUPPLIER], nif="NIF-INT1-001"
        )
        alert = DuplicateAlert.objects.get(partner=second)

    event = EventLog.objects.get(
        event_type="partners.duplicate_alert_created", tenant_id=str(tenant.id)
    )
    assert event.payload["alert_id"] == str(alert.id)
    assert event.payload["partner_id"] == str(second.id)
    assert event.payload["duplicate_of_id"] == str(first.id)


def test_no_duplicate_does_not_publish(tenant) -> None:
    with use_tenant(tenant.id):
        create_partner(tenant=tenant, name="Solo", roles=[Partner.ROLE_CLIENT], nif="NIF-INT1-002")

    assert not EventLog.objects.filter(
        event_type="partners.duplicate_alert_created", tenant_id=str(tenant.id)
    ).exists()


def test_notify_role_of_duplicate_action_is_registered() -> None:
    action = get_registered_action("partners.notify_role_of_duplicate")
    assert action is not None
    assert action.module == "partners"


def test_notify_role_of_duplicate_action_notifies_role_members(tenant) -> None:
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="part-int1-notify@example.com", password="Str0ngPassw0rd!23"
        )
        group, _ = Group.objects.get_or_create(name="resp_commercial")
        user.groups.add(group)
        UserTenantMembership.objects.create(tenant=tenant, user=user)

        action = get_registered_action("partners.notify_role_of_duplicate")
        assert action is not None
        action.function(
            str(tenant.id),
            {"role_code": "resp_commercial", "note": "Doublon de partenaire detecte"},
        )

        assert Notification.objects.filter(
            user=user, notification_type="partners.automation_alert"
        ).exists()
