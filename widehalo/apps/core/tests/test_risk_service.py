"""Tests du service `apps.core.services.risk` (RSK1-2) : calcul du score
derive, seuil de publication de l'evenement `risk.flagged`."""

from __future__ import annotations

import pytest

from apps.core.models.event import EventLog
from apps.core.models.risk import (
    CATEGORY_SUPPLIER,
    HIGH_SCORE_THRESHOLD,
    STATUS_CLOSED,
)
from apps.core.services.risk import close_risk_item, create_risk_item, update_risk_item
from apps.core.tests.factories import TenantFactory, UserFactory
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def test_create_risk_item_computes_score_from_likelihood_and_impact() -> None:
    tenant = TenantFactory()
    owner = UserFactory()

    with use_tenant(tenant.id):
        risk_item = create_risk_item(
            tenant=tenant, category=CATEGORY_SUPPLIER, likelihood=3, impact=2, owner=owner
        )

    assert risk_item.score == 6


def test_create_risk_item_above_threshold_publishes_risk_flagged() -> None:
    tenant = TenantFactory()
    owner = UserFactory()
    assert HIGH_SCORE_THRESHOLD <= 5 * 4

    with use_tenant(tenant.id):
        risk_item = create_risk_item(
            tenant=tenant, category=CATEGORY_SUPPLIER, likelihood=5, impact=4, owner=owner
        )

    assert risk_item.score == 20
    event = EventLog.objects.get(event_type="risk.flagged", tenant_id=str(tenant.id))
    assert event.payload["risk_item_id"] == str(risk_item.id)
    assert event.payload["score"] == 20


def test_create_risk_item_below_threshold_does_not_publish() -> None:
    tenant = TenantFactory()
    owner = UserFactory()
    assert HIGH_SCORE_THRESHOLD > 2 * 2

    with use_tenant(tenant.id):
        create_risk_item(
            tenant=tenant, category=CATEGORY_SUPPLIER, likelihood=2, impact=2, owner=owner
        )

    assert not EventLog.objects.filter(event_type="risk.flagged", tenant_id=str(tenant.id)).exists()


def test_update_risk_item_recomputes_score() -> None:
    tenant = TenantFactory()
    owner = UserFactory()

    with use_tenant(tenant.id):
        risk_item = create_risk_item(
            tenant=tenant, category=CATEGORY_SUPPLIER, likelihood=2, impact=2, owner=owner
        )
        update_risk_item(risk_item, likelihood=4, impact=4)
        risk_item.refresh_from_db()

    assert risk_item.score == 16


def test_update_risk_item_publishes_only_when_crossing_threshold() -> None:
    tenant = TenantFactory()
    owner = UserFactory()

    with use_tenant(tenant.id):
        risk_item = create_risk_item(
            tenant=tenant, category=CATEGORY_SUPPLIER, likelihood=2, impact=2, owner=owner
        )
        assert not EventLog.objects.filter(
            event_type="risk.flagged", tenant_id=str(tenant.id)
        ).exists()

        # Franchit le seuil (4 -> 20) : publie une premiere fois.
        update_risk_item(risk_item, likelihood=5, impact=4)
        assert (
            EventLog.objects.filter(event_type="risk.flagged", tenant_id=str(tenant.id)).count()
            == 1
        )

        # Reste au-dessus du seuil (20 -> 16) : pas de republication.
        update_risk_item(risk_item, likelihood=4, impact=4)
        assert (
            EventLog.objects.filter(event_type="risk.flagged", tenant_id=str(tenant.id)).count()
            == 1
        )


def test_close_risk_item_sets_status_closed() -> None:
    tenant = TenantFactory()
    owner = UserFactory()

    with use_tenant(tenant.id):
        risk_item = create_risk_item(
            tenant=tenant, category=CATEGORY_SUPPLIER, likelihood=1, impact=1, owner=owner
        )
        close_risk_item(risk_item, closed_by=owner)
        risk_item.refresh_from_db()

    assert risk_item.status == STATUS_CLOSED
