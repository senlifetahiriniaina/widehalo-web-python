"""Bloc F, F4 (FOR-15) : `services.expiry_alerts.list_expiring_lots`/
`check_expiring_lots` — détection des lots dont la date limite de
péremption est atteinte ou approche, avec stock réellement disponible.
Même patron que `apps.quality.tests.test_alerts` (D3, QUA-9)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group

from apps.core.models.notification import Notification
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkQualityState
from apps.stocks.services.expiry_alerts import (
    NOTIFICATION_ROLES,
    check_expiring_lots,
    list_expiring_lots,
)
from apps.stocks.services.quality import set_quality_state
from apps.stocks.tests.factories import StkLotFactory, StkQuantFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    t = Tenant.objects.create(code="STK-EXP", name="Stocks Expiry Tenant")
    with use_tenant(t.id):
        yield t


@pytest.fixture
def notified_users(tenant):
    """Un utilisateur par rôle de `NOTIFICATION_ROLES`, rattaché au
    tenant — même patron exact que `apps.quality.tests.test_alerts`."""
    users = {}
    with use_tenant(tenant.id):
        for role_code in NOTIFICATION_ROLES:
            user = User.objects.create_user(
                email=f"{role_code}-exp@example.com", password="Str0ngPassw0rd!23"
            )
            group, _created = Group.objects.get_or_create(name=role_code)
            user.groups.add(group)
            UserTenantMembership.objects.create(user=user, tenant=tenant)
            users[role_code] = user
    return users


TODAY = dt.date(2026, 6, 15)


def test_lot_far_from_expiry_is_not_flagged(tenant, notified_users) -> None:
    with use_tenant(tenant.id):
        lot = StkLotFactory(tenant=tenant, date_expiry=TODAY + dt.timedelta(days=90))
        StkQuantFactory(tenant=tenant, variant_id=lot.variant_id, lot=lot, qty=Decimal(10))

        assert list_expiring_lots(tenant, today=TODAY) == []


def test_lot_within_threshold_is_flagged_with_correct_days(tenant, notified_users) -> None:
    with use_tenant(tenant.id):
        lot = StkLotFactory(
            tenant=tenant, name="LOT-EXP-001", date_expiry=TODAY + dt.timedelta(days=10)
        )
        StkQuantFactory(tenant=tenant, variant_id=lot.variant_id, lot=lot, qty=Decimal(10))

        results = list_expiring_lots(tenant, today=TODAY)

        assert len(results) == 1
        assert results[0]["lot_name"] == "LOT-EXP-001"
        assert results[0]["days_until_expiry"] == 10
        assert results[0]["remaining_qty"] == Decimal(10)


def test_already_expired_lot_with_stock_is_flagged_with_negative_days(
    tenant, notified_users
) -> None:
    """ "Date limite de lot" (texte du plan) couvre aussi un lot DÉJÀ
    périmé — le cas le plus urgent, jamais exclu."""
    with use_tenant(tenant.id):
        lot = StkLotFactory(tenant=tenant, date_expiry=TODAY - dt.timedelta(days=5))
        StkQuantFactory(tenant=tenant, variant_id=lot.variant_id, lot=lot, qty=Decimal(4))

        results = list_expiring_lots(tenant, today=TODAY)

        assert len(results) == 1
        assert results[0]["days_until_expiry"] == -5


def test_lot_without_date_expiry_is_never_flagged(tenant, notified_users) -> None:
    with use_tenant(tenant.id):
        lot = StkLotFactory(tenant=tenant, date_expiry=None)
        StkQuantFactory(tenant=tenant, variant_id=lot.variant_id, lot=lot, qty=Decimal(10))

        assert list_expiring_lots(tenant, today=TODAY) == []


def test_lot_without_remaining_stock_is_never_flagged(tenant, notified_users) -> None:
    with use_tenant(tenant.id):
        lot = StkLotFactory(tenant=tenant, date_expiry=TODAY + dt.timedelta(days=1))
        StkQuantFactory(
            tenant=tenant,
            variant_id=lot.variant_id,
            lot=lot,
            qty=Decimal(10),
            qty_reserved=Decimal(10),
        )

        assert list_expiring_lots(tenant, today=TODAY) == []


def test_held_lot_is_never_flagged(tenant, notified_users) -> None:
    with use_tenant(tenant.id):
        lot = StkLotFactory(tenant=tenant, date_expiry=TODAY + dt.timedelta(days=1))
        StkQuantFactory(tenant=tenant, variant_id=lot.variant_id, lot=lot, qty=Decimal(10))
        set_quality_state(
            tenant=tenant,
            lot=lot,
            state=StkQualityState.STATE_EN_QUARANTAINE,
            description="Suspicion de non-conformité",
        )

        assert list_expiring_lots(tenant, today=TODAY) == []


def test_results_are_sorted_by_date_expiry_ascending(tenant, notified_users) -> None:
    with use_tenant(tenant.id):
        lot_later = StkLotFactory(
            tenant=tenant, name="LOT-LATER", date_expiry=TODAY + dt.timedelta(days=20)
        )
        StkQuantFactory(
            tenant=tenant, variant_id=lot_later.variant_id, lot=lot_later, qty=Decimal(1)
        )
        lot_sooner = StkLotFactory(
            tenant=tenant, name="LOT-SOONER", date_expiry=TODAY + dt.timedelta(days=1)
        )
        StkQuantFactory(
            tenant=tenant, variant_id=lot_sooner.variant_id, lot=lot_sooner, qty=Decimal(1)
        )

        results = list_expiring_lots(tenant, today=TODAY)

        assert [r["lot_name"] for r in results] == ["LOT-SOONER", "LOT-LATER"]


def test_list_expiring_lots_never_sends_a_notification(tenant, notified_users) -> None:
    """Distinction centrale du sprint : la variante lecture seule (utilisée
    par le tableau de bord) ne doit jamais renvoyer une notification."""
    with use_tenant(tenant.id):
        lot = StkLotFactory(tenant=tenant, date_expiry=TODAY)
        StkQuantFactory(tenant=tenant, variant_id=lot.variant_id, lot=lot, qty=Decimal(1))

        list_expiring_lots(tenant, today=TODAY)

        assert not Notification.objects.filter(notification_type="stocks.lot_expiring").exists()


def test_check_expiring_lots_notifies_every_role(tenant, notified_users) -> None:
    with use_tenant(tenant.id):
        lot = StkLotFactory(tenant=tenant, date_expiry=TODAY)
        StkQuantFactory(tenant=tenant, variant_id=lot.variant_id, lot=lot, qty=Decimal(1))

        results = check_expiring_lots(tenant, today=TODAY)

        assert len(results) == 1
        assert Notification.objects.filter(notification_type="stocks.lot_expiring").count() == len(
            NOTIFICATION_ROLES
        )
        for user in notified_users.values():
            assert Notification.objects.filter(
                user=user, notification_type="stocks.lot_expiring"
            ).exists()


def test_tenant_without_any_lot_returns_empty_list(tenant) -> None:
    with use_tenant(tenant.id):
        assert list_expiring_lots(tenant, today=TODAY) == []
