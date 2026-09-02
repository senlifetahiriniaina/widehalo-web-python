"""Tests du gap PT8 (chantier "fiche partenaire a onglets par role") sur
le contrat public de `logistics` : `list_shipments_for_partner`."""

from __future__ import annotations

import uuid

import pytest

from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant
from apps.logistics.services.public import list_shipments_for_partner
from apps.logistics.tests.factories import LogServiceProviderFactory, LogShipmentFactory

pytestmark = pytest.mark.django_db


def test_list_shipments_for_partner_returns_rows_for_the_rattached_carrier() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        partner_id = uuid.uuid4()
        carrier = LogServiceProviderFactory(tenant=tenant, partner_id=partner_id)
        shipment = LogShipmentFactory(tenant=tenant, carrier=carrier)
        other_carrier = LogServiceProviderFactory(tenant=tenant)
        LogShipmentFactory(tenant=tenant, carrier=other_carrier)  # other partner

        rows = list_shipments_for_partner(partner_id)

        assert len(rows) == 1
        assert rows[0]["id"] == shipment.id
        assert rows[0]["reference"] == shipment.reference
        assert rows[0]["origin"] == shipment.origin
        assert rows[0]["destination"] == shipment.destination
        assert rows[0]["state"] == shipment.state


def test_list_shipments_for_partner_returns_empty_list_for_unrattached_partner() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        assert list_shipments_for_partner(uuid.uuid4()) == []


def test_list_shipments_for_partner_ignores_carrier_with_no_partner_id() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        carrier = LogServiceProviderFactory(tenant=tenant)  # partner_id left None
        LogShipmentFactory(tenant=tenant, carrier=carrier)

        assert list_shipments_for_partner(uuid.uuid4()) == []
