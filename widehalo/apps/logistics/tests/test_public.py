"""Tests du contrat public de `logistics` (`apps/logistics/services/public.py`)
— seule surface que les autres apps metier ont le droit d'importer. Couvre
B2 (Phase 3, "chronologie unifiee CREDOC/import/cout debarque", cf. plan) :
`list_shipments_for_purchase_order`/`get_shipment_transition_history`."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from django.contrib.contenttypes.models import ContentType

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.models.workflow import StateTransitionLog
from apps.core.tests.utils import use_tenant
from apps.logistics.services.public import (
    get_shipment_transition_history,
    list_shipments_for_purchase_order,
)
from apps.logistics.services.shipments import book_shipment, create_shipment
from apps.logistics.tests.factories import LogCustomsFileFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def shipment_public_setup():
    tenant = Tenant.objects.create(code="LOG-PUB-SHP", name="Logistics Public Shipment Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="log-pub-shp@example.com", password="Str0ngPassw0rd!23"
        )
        return tenant, user


def test_list_shipments_for_purchase_order_finds_shipment_by_list_membership(
    shipment_public_setup,
) -> None:
    """`LogShipment.purchase_order_ids` est une LISTE JSONField — le lookup
    doit fonctionner par appartenance (containment), pas par egalite
    exacte de la liste entiere."""
    tenant, _user = shipment_public_setup
    order_id = uuid.uuid4()
    other_order_id = uuid.uuid4()
    with use_tenant(tenant.id):
        shipment = create_shipment(
            tenant,
            origin="Guangzhou",
            destination="Toamasina",
            purchase_order_ids=[order_id, other_order_id],
        )
        create_shipment(
            tenant, origin="Shenzhen", destination="Toamasina", purchase_order_ids=[uuid.uuid4()]
        )

        results = list_shipments_for_purchase_order(order_id)

        assert len(results) == 1
        assert results[0]["id"] == shipment.id
        assert results[0]["reference"] == shipment.reference
        assert results[0]["origin"] == "Guangzhou"
        assert results[0]["customs_files"] == []
        assert results[0]["history"] == []


def test_list_shipments_for_purchase_order_includes_history_and_customs_files(
    shipment_public_setup,
) -> None:
    tenant, user = shipment_public_setup
    order_id = uuid.uuid4()
    with use_tenant(tenant.id):
        shipment = create_shipment(
            tenant, origin="Guangzhou", destination="Toamasina", purchase_order_ids=[order_id]
        )
        book_shipment(shipment, user)
        customs_file = LogCustomsFileFactory(
            tenant=tenant, shipment=shipment, opened_at=dt.date(2026, 2, 1)
        )

        results = list_shipments_for_purchase_order(order_id)

        assert len(results) == 1
        assert results[0]["state"] == "booked"
        assert len(results[0]["history"]) == 1
        assert results[0]["history"][0]["from_state"] == "planned"
        assert results[0]["history"][0]["to_state"] == "booked"
        assert len(results[0]["customs_files"]) == 1
        assert results[0]["customs_files"][0]["id"] == customs_file.id
        assert results[0]["customs_files"][0]["opened_at"] == dt.date(2026, 2, 1)


def test_list_shipments_for_purchase_order_returns_empty_list_without_match(
    shipment_public_setup,
) -> None:
    tenant, _user = shipment_public_setup
    with use_tenant(tenant.id):
        assert list_shipments_for_purchase_order(uuid.uuid4()) == []


def test_get_shipment_transition_history_excludes_refused_attempts(shipment_public_setup) -> None:
    """Un refus de permission (`was_refused=True`, journalise par
    `apps.core.services.workflow.attempt_transition`) n'est pas une VRAIE
    transition — ne doit jamais apparaitre dans une frise chronologique."""
    tenant, user = shipment_public_setup
    with use_tenant(tenant.id):
        from apps.logistics.models import LogShipment

        shipment = create_shipment(tenant, origin="Guangzhou", destination="Toamasina")
        StateTransitionLog.objects.create(
            content_type=ContentType.objects.get_for_model(LogShipment),
            object_id=str(shipment.id),
            field_name="state",
            from_state="planned",
            to_state="planned",
            performed_by=user,
            was_refused=True,
            comment="Tentative refusee",
        )

        assert get_shipment_transition_history(shipment.id) == []


def test_get_shipment_transition_history_returns_empty_list_for_unknown_shipment(
    shipment_public_setup,
) -> None:
    tenant, _user = shipment_public_setup
    with use_tenant(tenant.id):
        assert get_shipment_transition_history(uuid.uuid4()) == []
