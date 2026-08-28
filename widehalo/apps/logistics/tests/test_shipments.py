from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounting.models import AccAccount, AccJournal, AccMove
from apps.accounting.tests.factories import AccAccountFactory, AccJournalFactory, AccPeriodFactory
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.logistics.services.freight import create_service_provider
from apps.logistics.services.shipments import (
    add_shipment_leg,
    block_shipment,
    book_shipment,
    close_shipment,
    create_shipment,
    deliver_shipment,
    mark_shipment_arrived_at_port,
    mark_shipment_customs_cleared,
    mark_shipment_in_transit,
    pick_up_shipment,
    refactor_freight_to_customer,
    start_shipment_customs_clearance,
    unblock_shipment,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def shipment_setup():
    tenant = Tenant.objects.create(code="LOG-SHP-T", name="Logistics Shipment Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="log-shp@example.com", password="Str0ngPassw0rd!23")
        carrier = create_service_provider(tenant, code="CAR1", name="Transporteur Maritime")
        shipment = create_shipment(
            tenant, origin="Guangzhou", destination="Toamasina", carrier=carrier
        )
        return tenant, user, shipment


def test_create_shipment_and_add_leg(shipment_setup) -> None:
    tenant, _user, shipment = shipment_setup
    with use_tenant(tenant.id):
        leg1 = add_shipment_leg(shipment, mode="sea", origin="Guangzhou", destination="Toamasina")
        leg2 = add_shipment_leg(
            shipment, mode="road", origin="Toamasina", destination="Antananarivo"
        )
        assert leg1.sequence == 1
        assert leg2.sequence == 2


def test_shipment_full_lifecycle(shipment_setup) -> None:
    tenant, user, shipment = shipment_setup
    with use_tenant(tenant.id):
        book_shipment(shipment, user)
        pick_up_shipment(shipment, user)
        mark_shipment_in_transit(shipment, user)
        mark_shipment_arrived_at_port(shipment, user)
        start_shipment_customs_clearance(shipment, user)
        mark_shipment_customs_cleared(shipment, user)
        deliver_shipment(shipment, user)
        close_shipment(shipment, user)

        shipment.refresh_from_db()
        assert shipment.state == "closed"


def test_block_and_unblock_shipment(shipment_setup) -> None:
    tenant, user, shipment = shipment_setup
    with use_tenant(tenant.id):
        book_shipment(shipment, user)
        pick_up_shipment(shipment, user)
        mark_shipment_in_transit(shipment, user)

        block_shipment(shipment, user, reason="Document douanier manquant")
        shipment.refresh_from_db()
        assert shipment.state == "blocked"
        assert shipment.block_reason == "Document douanier manquant"

        unblock_shipment(shipment, user)
        shipment.refresh_from_db()
        assert shipment.state == "in_transit"


def test_block_shipment_requires_reason(shipment_setup) -> None:
    tenant, user, shipment = shipment_setup
    with use_tenant(tenant.id):
        book_shipment(shipment, user)
        with pytest.raises(ValidationError):
            block_shipment(shipment, user, reason="")


def test_refactor_freight_to_customer_creates_draft_invoice(shipment_setup) -> None:
    tenant, _user, shipment = shipment_setup
    with use_tenant(tenant.id):
        AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_SALE)
        AccPeriodFactory(
            tenant=tenant, date_start=dt.date(2026, 1, 1), date_end=dt.date(2026, 1, 31)
        )
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_RECEIVABLE)
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_INCOME)

        shipment.freight_cost_mga = Decimal("300000")
        shipment.save(update_fields=["freight_cost_mga"])

        partner_id = uuid.uuid4()
        move_id = refactor_freight_to_customer(
            shipment, partner_id=partner_id, date=dt.date(2026, 1, 15)
        )

        assert move_id is not None
        move = AccMove.objects.get(id=move_id)
        assert move.state == AccMove.STATE_DRAFT
        assert move.partner_id == partner_id
        shipment.refresh_from_db()
        assert shipment.freight_billed_to_customer_mga == Decimal("300000")


def test_refactor_freight_to_customer_returns_none_without_accounting_config(
    shipment_setup,
) -> None:
    tenant, _user, shipment = shipment_setup
    with use_tenant(tenant.id):
        result = refactor_freight_to_customer(shipment, partner_id=uuid.uuid4())
        assert result is None
