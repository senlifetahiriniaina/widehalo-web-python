"""INT1 (chantier interactivite native inter-modules) : evenement
`financing.credoc_state_changed`, publie a CHAQUE transition du cycle de
vie RUU 600 (`services/credoc.py`)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.core.models.event import EventLog
from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import grant_role, use_tenant
from apps.financing.models import FinCredoc
from apps.financing.services.credoc import (
    close_credoc,
    create_credoc,
    open_credoc,
    pay_credoc,
    receive_documents,
)

pytestmark = pytest.mark.django_db


def _credoc(tenant: Tenant) -> FinCredoc:
    return create_credoc(
        tenant,
        purchase_order_id=uuid.uuid4(),
        bank="Banque emettrice",
        beneficiary="Fournisseur import",
        amount_mga=Decimal("30000000"),
        validity_date=dt.date(2026, 12, 31),
    )


def test_open_credoc_publishes_credoc_state_changed() -> None:
    tenant = Tenant.objects.create(code="FIN-INT1-CRED1", name="Financing INT1 Credoc Tenant 1")
    with use_tenant(tenant.id):
        user = UserFactory()
        grant_role(user, "comptable")
        credoc = _credoc(tenant)

        open_credoc(credoc, user, reason="Accord de la banque émettrice reçu")

    event = EventLog.objects.get(
        event_type="financing.credoc_state_changed", tenant_id=str(tenant.id)
    )
    assert event.payload["credoc_id"] == str(credoc.id)
    assert event.payload["state"] == FinCredoc.STATE_OPENED
    # B2 : le motif rejoint desormais le payload de l'evenement — meme
    # discipline que `purchase.dispute_opened`/`logistics.shipment_blocked`.
    assert event.payload["reason"] == "Accord de la banque émettrice reçu"


def test_each_transition_publishes_its_own_event() -> None:
    tenant = Tenant.objects.create(code="FIN-INT1-CRED2", name="Financing INT1 Credoc Tenant 2")
    with use_tenant(tenant.id):
        user = UserFactory()
        grant_role(user, "comptable")
        credoc = _credoc(tenant)

        open_credoc(credoc, user, reason="Accord de la banque émettrice reçu")
        receive_documents(credoc, user, reason="Jeu de documents complet reçu")
        pay_credoc(credoc, user, reason="Documents conformes, paiement autorisé")
        close_credoc(credoc, user, reason="Marchandise livrée, dossier soldé")

    events = list(
        EventLog.objects.filter(
            event_type="financing.credoc_state_changed", tenant_id=str(tenant.id)
        ).order_by("created_at")
    )
    assert [e.payload["state"] for e in events] == [
        FinCredoc.STATE_OPENED,
        FinCredoc.STATE_DOCUMENTS_RECEIVED,
        FinCredoc.STATE_PAID,
        FinCredoc.STATE_CLOSED,
    ]
