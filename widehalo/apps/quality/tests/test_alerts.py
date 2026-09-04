"""Bloc D, D3 (QUA-9) : `check_overdue_controls` — compare
`QltControlPlan.frequency_days` au dernier contrôle réel par lot, notifie
`NOTIFICATION_ROLES` au-delà du seuil. Périmètre assumé (cf. docstring de
`services/alerts.py`) : seuls les lots déjà mesurés au moins une fois
peuvent être détectés en retard."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.utils import timezone

from apps.core.models.notification import Notification
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.tests.utils import use_tenant
from apps.quality.services.alerts import NOTIFICATION_ROLES, check_overdue_controls
from apps.quality.services.control_plans import add_critical_point, create_control_plan
from apps.quality.services.measurements import record_measurement
from apps.stocks.tests.factories import StkLotFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    t = Tenant.objects.create(code="QLT-ALERT", name="Quality Alerts Tenant")
    with use_tenant(t.id):
        yield t


@pytest.fixture
def notified_users(tenant):
    """Un utilisateur par rôle de `NOTIFICATION_ROLES`, rattaché au
    tenant — même patron exact que `test_price_watch.py`."""
    users = {}
    with use_tenant(tenant.id):
        for role_code in NOTIFICATION_ROLES:
            user = User.objects.create_user(
                email=f"{role_code}-qlt@example.com", password="Str0ngPassw0rd!23"
            )
            group, _created = Group.objects.get_or_create(name=role_code)
            user.groups.add(group)
            UserTenantMembership.objects.create(user=user, tenant=tenant)
            users[role_code] = user
    return users


@pytest.fixture
def measurer(tenant):
    with use_tenant(tenant.id):
        return User.objects.create_user(
            email="mesureur-qlt@example.com", password="Str0ngPassw0rd!23"
        )


def test_lot_measured_recently_is_not_flagged(tenant, measurer, notified_users) -> None:
    with use_tenant(tenant.id):
        plan = create_control_plan(tenant=tenant, name="Cuisson", frequency_days=7)
        point = add_critical_point(plan, name="Température", limit_min=Decimal(70))
        lot = StkLotFactory(tenant=tenant, name="LOT-ALERT-001")
        now = timezone.now()
        record_measurement(
            point,
            tenant=tenant,
            value=Decimal(80),
            measured_by=measurer,
            lot_variant_id=lot.variant_id,
            lot_name=lot.name,
            measured_at=now - timedelta(days=1),
        )

        results = check_overdue_controls(tenant, now=now)

        assert results == []
        assert not Notification.objects.filter(notification_type="quality.control_overdue").exists()


def test_lot_measured_beyond_frequency_is_flagged_and_notified(
    tenant, measurer, notified_users
) -> None:
    with use_tenant(tenant.id):
        plan = create_control_plan(tenant=tenant, name="Cuisson", frequency_days=7)
        point = add_critical_point(plan, name="Température", limit_min=Decimal(70))
        lot = StkLotFactory(tenant=tenant, name="LOT-ALERT-002")
        now = timezone.now()
        last_measured_at = now - timedelta(days=10)
        record_measurement(
            point,
            tenant=tenant,
            value=Decimal(80),
            measured_by=measurer,
            lot_variant_id=lot.variant_id,
            lot_name=lot.name,
            measured_at=last_measured_at,
        )

        results = check_overdue_controls(tenant, now=now)

        assert len(results) == 1
        assert results[0]["lot_name"] == lot.name
        assert results[0]["days_overdue"] == 3
        assert Notification.objects.filter(
            notification_type="quality.control_overdue"
        ).count() == len(NOTIFICATION_ROLES)
        for user in notified_users.values():
            assert Notification.objects.filter(
                user=user, notification_type="quality.control_overdue"
            ).exists()


def test_zero_frequency_is_never_flagged(tenant, measurer, notified_users) -> None:
    with use_tenant(tenant.id):
        plan = create_control_plan(tenant=tenant, name="Cuisson")  # frequency_days=0 (défaut)
        point = add_critical_point(plan, name="Température", limit_min=Decimal(70))
        lot = StkLotFactory(tenant=tenant, name="LOT-ALERT-003")
        now = timezone.now()
        record_measurement(
            point,
            tenant=tenant,
            value=Decimal(80),
            measured_by=measurer,
            lot_variant_id=lot.variant_id,
            lot_name=lot.name,
            measured_at=now - timedelta(days=365),
        )

        results = check_overdue_controls(tenant, now=now)

        assert results == []


def test_lot_never_measured_is_not_detected(tenant, notified_users) -> None:
    """Périmètre assumé du sprint : un plan sans aucune mesure ne peut
    signaler aucun lot — pas de population de lots à énumérer sans
    mesure préalable (cf. Contexte du plan D3)."""
    with use_tenant(tenant.id):
        create_control_plan(tenant=tenant, name="Réception matière", frequency_days=1)

        results = check_overdue_controls(tenant)

        assert results == []


def test_measurement_without_lot_is_never_flagged(tenant, measurer, notified_users) -> None:
    with use_tenant(tenant.id):
        plan = create_control_plan(tenant=tenant, name="Audit interne", frequency_days=1)
        point = add_critical_point(plan, name="Score", limit_min=Decimal(0))
        now = timezone.now()
        record_measurement(
            point,
            tenant=tenant,
            value=Decimal(10),
            measured_by=measurer,
            measured_at=now - timedelta(days=30),
        )

        results = check_overdue_controls(tenant, now=now)

        assert results == []


def test_uses_most_recent_measurement_across_critical_points(
    tenant, measurer, notified_users
) -> None:
    """`frequency_days` vit sur le plan — le « dernier contrôle » agrège
    le max sur tous les points critiques, pas un seul isolé."""
    with use_tenant(tenant.id):
        plan = create_control_plan(tenant=tenant, name="Cuisson", frequency_days=7)
        point_a = add_critical_point(plan, name="Température", limit_min=Decimal(70))
        point_b = add_critical_point(plan, name="pH", limit_min=Decimal(4))
        lot = StkLotFactory(tenant=tenant, name="LOT-ALERT-004")
        now = timezone.now()
        record_measurement(
            point_a,
            tenant=tenant,
            value=Decimal(80),
            measured_by=measurer,
            lot_variant_id=lot.variant_id,
            lot_name=lot.name,
            measured_at=now - timedelta(days=20),
        )
        record_measurement(
            point_b,
            tenant=tenant,
            value=Decimal(5),
            measured_by=measurer,
            lot_variant_id=lot.variant_id,
            lot_name=lot.name,
            measured_at=now - timedelta(days=1),
        )

        results = check_overdue_controls(tenant, now=now)

        assert results == []
