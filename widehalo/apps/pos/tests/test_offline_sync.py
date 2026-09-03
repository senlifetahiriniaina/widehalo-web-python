"""Synchronisation hors ligne (POS-3, POS-4) : `client_uuid` comme clef
d'idempotence — un rejeu du même `client_uuid` (perte de réseau + nouvel
essai) ne doit jamais créer deux commandes ni doubler un mouvement de
stock ou une écriture."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.pos.models import PosOrder, PosOrderLine, PosSession, PosSyncLog
from apps.pos.services.orders import sync_order
from apps.pos.tests.factories import PosPaymentMethodFactory, PosSessionFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    t = Tenant.objects.create(code="POS-SYNC", name="POS Sync Tenant")
    with use_tenant(t.id):
        yield t


def _sale_payload(client_uuid, method_id):
    return {
        "session": None,  # rempli par l'appelant
        "client_uuid": client_uuid,
        "local_sequence": 1,
        "order_type": PosOrder.TYPE_SALE,
        "document_type": PosOrder.DOCUMENT_TICKET,
        "partner_id": None,
        "lines": [
            {
                "line_type": PosOrderLine.TYPE_SERVICE,
                "description": "Prestation",
                "qty": Decimal(1),
                "unit_price": Decimal(1000),
            }
        ],
        "payments": [{"method_id": method_id, "amount": Decimal(1000)}],
        "source": PosOrder.SOURCE_OFFLINE,
    }


def test_replaying_the_same_client_uuid_never_creates_a_second_order(tenant) -> None:
    session = PosSessionFactory(tenant=tenant)
    method = PosPaymentMethodFactory(tenant=tenant, type="cash")
    client_uuid = uuid.uuid4()

    payload = _sale_payload(client_uuid, method.id)
    payload["session"] = session

    order1, outcome1 = sync_order(tenant, date=dt.date(2026, 1, 15), **payload)
    assert outcome1 == PosSyncLog.OUTCOME_ACCEPTED
    assert order1.state == PosOrder.STATE_VALIDATED

    order2, outcome2 = sync_order(tenant, date=dt.date(2026, 1, 15), **payload)
    assert outcome2 == PosSyncLog.OUTCOME_DUPLICATE
    assert order2.id == order1.id

    assert PosOrder.objects.filter(client_uuid=client_uuid).count() == 1
    assert PosSyncLog.objects.filter(client_uuid=client_uuid).count() == 2


def test_a_rejected_sync_leaves_no_partial_order_behind(tenant) -> None:
    session = PosSessionFactory(tenant=tenant)
    session.state = PosSession.STATE_CLOSED
    session.save(update_fields=["state"])
    method = PosPaymentMethodFactory(tenant=tenant, type="cash")
    client_uuid = uuid.uuid4()

    payload = _sale_payload(client_uuid, method.id)
    payload["session"] = session

    with pytest.raises(ValidationError):
        sync_order(tenant, date=dt.date(2026, 1, 15), **payload)

    assert not PosOrder.objects.filter(client_uuid=client_uuid).exists()
    log = PosSyncLog.objects.get(client_uuid=client_uuid)
    assert log.outcome == PosSyncLog.OUTCOME_REJECTED
