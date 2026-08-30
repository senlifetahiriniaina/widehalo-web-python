"""INT1 (chantier interactivite native inter-modules) : evenement
`patronage.pattern_version_changed` (`services/patterns.py::
new_pattern_version`) et action `patronage.notify_role_of_pattern_version`
enregistree dans `core.services.automation_registry`."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group

from apps.core.models.event import EventLog
from apps.core.models.notification import Notification
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.services.automation_registry import get_registered_action
from apps.core.tests.utils import use_tenant
from apps.patronage.models import PatSizeChart
from apps.patronage.services.patterns import create_pattern, new_pattern_version

pytestmark = pytest.mark.django_db


@pytest.fixture
def pattern_setup():
    tenant = Tenant.objects.create(code="PAT-INT1-PAT", name="Patronage INT1 Pattern Tenant")
    with use_tenant(tenant.id):
        size_chart = PatSizeChart.objects.create(
            tenant=tenant,
            code="CHEMISE-H",
            name="Chemise homme",
            garment_type=PatSizeChart.GARMENT_SHIRT,
            sizes=["S", "M", "L"],
            base_size="S",
        )
        pattern = create_pattern(
            tenant=tenant, code="PAT-INT1-1", name="Chemise classique", size_chart=size_chart
        )
        return tenant, pattern


def test_new_pattern_version_publishes_pattern_version_changed(pattern_setup) -> None:
    tenant, pattern = pattern_setup
    with use_tenant(tenant.id):
        v2 = new_pattern_version(pattern)

    event = EventLog.objects.get(
        event_type="patronage.pattern_version_changed", tenant_id=str(tenant.id)
    )
    assert event.payload["pattern_id"] == str(v2.id)
    assert event.payload["parent_pattern_id"] == str(pattern.id)
    assert event.payload["version"] == 2


def test_notify_role_of_pattern_version_action_is_registered() -> None:
    action = get_registered_action("patronage.notify_role_of_pattern_version")
    assert action is not None
    assert action.module == "patronage"


def test_notify_role_of_pattern_version_action_notifies_role_members(pattern_setup) -> None:
    tenant, _pattern = pattern_setup
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="pat-int1-notify@example.com", password="Str0ngPassw0rd!23"
        )
        group, _ = Group.objects.get_or_create(name="resp_production")
        user.groups.add(group)
        UserTenantMembership.objects.create(tenant=tenant, user=user)

        action = get_registered_action("patronage.notify_role_of_pattern_version")
        assert action is not None
        action.function(
            str(tenant.id),
            {"role_code": "resp_production", "note": "Nouvelle version de patron"},
        )

        assert Notification.objects.filter(
            user=user, notification_type="patronage.automation_alert"
        ).exists()
