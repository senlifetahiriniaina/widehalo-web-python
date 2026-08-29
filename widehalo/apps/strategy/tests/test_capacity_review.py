"""Tests du service de calcul CAP1-2 (cf. plan, chantier « capacite de
charge a 90 jours ») : `apps/strategy/services/capacity_review.py`."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.models.notification import Notification
from apps.core.models.tenant import Tenant
from apps.core.models.user import UserTenantMembership
from apps.core.services.reports_registry import get_registered_report
from apps.core.tenant_context import activate_tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import grant_role, use_tenant
from apps.mrp.tests.factories import (
    MrpOrderFactory,
    MrpRoutingFactory,
    MrpRoutingStepFactory,
    MrpWorkcenterFactory,
    MrpWorkshopFactory,
)
from apps.strategy.services.capacity_review import (
    DEFAULT_OVERLOAD_THRESHOLD_PCT,
    build_capacity_outlook,
)

pytestmark = pytest.mark.django_db


def _planned_at(days_from_today: int) -> dt.datetime:
    return timezone.make_aware(
        dt.datetime.combine(dt.date.today() + dt.timedelta(days=days_from_today), dt.time(8, 0))
    )


def test_build_capacity_outlook_aggregates_capacity_and_planned_workload() -> None:
    tenant = Tenant.objects.create(code="CAP-1", name="Capacite Tenant 1")
    with use_tenant(tenant.id):
        workshop = MrpWorkshopFactory(tenant=tenant, capacity_hours_day=Decimal("8"))
        routing = MrpRoutingFactory(tenant=tenant)
        MrpRoutingStepFactory(
            tenant=tenant,
            routing=routing,
            duration_min=120,
            workcenter=MrpWorkcenterFactory(tenant=tenant, workshop=workshop),
        )
        MrpOrderFactory(
            tenant=tenant,
            workshop=workshop,
            routing=routing,
            qty=Decimal("1"),
            date_planned_start=_planned_at(2),
        )

        outlook = build_capacity_outlook(tenant, horizon_days=14, notify=False)

        assert outlook["horizon_days"] == 14
        # 2 semaines (14 jours), aucune semaine partielle.
        assert len(outlook["weeks"]) == 2
        first_week = outlook["weeks"][0]
        # Capacite semaine 1 : 8h/jour * 7 jours = 56h.
        assert first_week["capacity_hours"] == Decimal("56")
        # Charge : 1 * 120 min / 60 = 2h, dans la 1ere semaine.
        assert first_week["planned_workload_hours"] == Decimal("2")
        assert first_week["orders_count"] == 1
        assert outlook["weeks"][1]["planned_workload_hours"] == Decimal("0")
        assert outlook["payroll_projection"]  # au moins un mois projete.


def test_build_capacity_outlook_below_threshold_does_not_notify() -> None:
    tenant = Tenant.objects.create(code="CAP-2", name="Capacite Tenant 2")
    with use_tenant(tenant.id):
        direction_user = UserFactory(email="direction-cap2@example.com")
        grant_role(direction_user, "direction")
        UserTenantMembership.objects.create(user=direction_user, tenant=tenant)

        workshop = MrpWorkshopFactory(tenant=tenant, capacity_hours_day=Decimal("100"))
        routing = MrpRoutingFactory(tenant=tenant)
        MrpRoutingStepFactory(
            tenant=tenant,
            routing=routing,
            duration_min=60,
            workcenter=MrpWorkcenterFactory(tenant=tenant, workshop=workshop),
        )
        MrpOrderFactory(
            tenant=tenant,
            workshop=workshop,
            routing=routing,
            qty=Decimal("1"),
            date_planned_start=_planned_at(1),
        )

        outlook = build_capacity_outlook(tenant, horizon_days=7)

        assert outlook["overloaded_week_starts"] == []
        assert not Notification.objects.filter(user=direction_user).exists()


def test_build_capacity_outlook_above_threshold_notifies_direction_and_resp_production() -> None:
    tenant = Tenant.objects.create(code="CAP-3", name="Capacite Tenant 3")
    with use_tenant(tenant.id):
        direction_user = UserFactory(email="direction-cap3@example.com")
        grant_role(direction_user, "direction")
        UserTenantMembership.objects.create(user=direction_user, tenant=tenant)
        resp_prod_user = UserFactory(email="respprod-cap3@example.com")
        grant_role(resp_prod_user, "resp_production")
        UserTenantMembership.objects.create(user=resp_prod_user, tenant=tenant)

        # Capacite tres faible face a une charge planifiee elevee.
        workshop = MrpWorkshopFactory(tenant=tenant, capacity_hours_day=Decimal("1"))
        routing = MrpRoutingFactory(tenant=tenant)
        MrpRoutingStepFactory(
            tenant=tenant,
            routing=routing,
            duration_min=600,
            workcenter=MrpWorkcenterFactory(tenant=tenant, workshop=workshop),
        )
        MrpOrderFactory(
            tenant=tenant,
            workshop=workshop,
            routing=routing,
            qty=Decimal("1"),
            date_planned_start=_planned_at(1),
        )

        outlook = build_capacity_outlook(
            tenant, horizon_days=7, overload_threshold_pct=DEFAULT_OVERLOAD_THRESHOLD_PCT
        )

        assert len(outlook["overloaded_week_starts"]) == 1
        assert Notification.objects.filter(
            user=direction_user, notification_type="strategy.capacity_overload"
        ).exists()
        assert Notification.objects.filter(
            user=resp_prod_user, notification_type="strategy.capacity_overload"
        ).exists()


def test_build_capacity_outlook_notify_false_never_notifies_even_above_threshold() -> None:
    tenant = Tenant.objects.create(code="CAP-4", name="Capacite Tenant 4")
    with use_tenant(tenant.id):
        direction_user = UserFactory(email="direction-cap4@example.com")
        grant_role(direction_user, "direction")
        UserTenantMembership.objects.create(user=direction_user, tenant=tenant)

        workshop = MrpWorkshopFactory(tenant=tenant, capacity_hours_day=Decimal("1"))
        routing = MrpRoutingFactory(tenant=tenant)
        MrpRoutingStepFactory(
            tenant=tenant,
            routing=routing,
            duration_min=600,
            workcenter=MrpWorkcenterFactory(tenant=tenant, workshop=workshop),
        )
        MrpOrderFactory(
            tenant=tenant,
            workshop=workshop,
            routing=routing,
            qty=Decimal("1"),
            date_planned_start=_planned_at(1),
        )

        outlook = build_capacity_outlook(tenant, horizon_days=7, notify=False)

        assert outlook["overloaded_week_starts"]
        assert not Notification.objects.filter(user=direction_user).exists()


def test_build_capacity_outlook_zero_capacity_never_flagged_overloaded() -> None:
    """Aucun atelier -> capacite nulle : `is_overloaded` reste faux (pas de
    division par zero, pas de faux positif d'un ratio "infini")."""
    tenant = Tenant.objects.create(code="CAP-5", name="Capacite Tenant 5")
    with use_tenant(tenant.id):
        outlook = build_capacity_outlook(tenant, horizon_days=7, notify=False)

        assert all(not week["is_overloaded"] for week in outlook["weeks"])
        assert outlook["overloaded_week_starts"] == []


def test_cap_90j_registered_render_rows_only_in_reporting_catalog() -> None:
    report = get_registered_report("CAP-90J")
    assert report is not None
    assert report.supports_rows()
    assert not report.supports_pdf()


def test_cap_90j_adapter_generates_rows_via_registry() -> None:
    tenant = Tenant.objects.create(code="CAP-6", name="Capacite Tenant 6")
    with activate_tenant(tenant.id):
        MrpWorkshopFactory(tenant=tenant, capacity_hours_day=Decimal("8"))
        report = get_registered_report("CAP-90J")
        assert report is not None
        assert report.render_rows is not None
        rows = report.render_rows({"horizon_days": 14}, None)
        assert len(rows) == 2
        assert rows[0]["semaine"] == 1
        assert "capacite_heures" in rows[0]
