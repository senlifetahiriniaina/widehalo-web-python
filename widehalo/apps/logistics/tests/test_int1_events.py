"""INT1 (chantier interactivite native inter-modules) : evenement
`logistics.shipment_blocked`, publie par `services/shipments.py::
block_shipment` — absent jusqu'ici (verifie par lecture directe)."""

from __future__ import annotations

import pytest

from apps.core.models.event import EventLog
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.logistics.services.freight import create_service_provider
from apps.logistics.services.shipments import (
    block_shipment,
    book_shipment,
    create_shipment,
    mark_shipment_in_transit,
    pick_up_shipment,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def shipment_setup():
    tenant = Tenant.objects.create(code="LOG-INT1-SHP", name="Logistics INT1 Shipment Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="log-int1-shp@example.com", password="Str0ngPassw0rd!23"
        )
        carrier = create_service_provider(tenant, code="CAR1", name="Transporteur Maritime")
        shipment = create_shipment(
            tenant, origin="Guangzhou", destination="Toamasina", carrier=carrier
        )
        return tenant, user, shipment


def test_block_shipment_publishes_shipment_blocked(shipment_setup) -> None:
    tenant, user, shipment = shipment_setup
    with use_tenant(tenant.id):
        book_shipment(shipment, user)
        pick_up_shipment(shipment, user)
        mark_shipment_in_transit(shipment, user)

        block_shipment(shipment, user, reason="Document douanier manquant")

    event = EventLog.objects.get(event_type="logistics.shipment_blocked", tenant_id=str(tenant.id))
    assert event.payload["shipment_id"] == str(shipment.id)
    assert event.payload["reason"] == "Document douanier manquant"
