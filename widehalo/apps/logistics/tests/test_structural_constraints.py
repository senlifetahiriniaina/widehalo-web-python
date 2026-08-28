"""T2 (couches 4-5 du CDC, §8) : contraintes structurelles/d'interdependance
au niveau base pour `logistics` — comble le trou laisse par la premiere
passe de verification des 14 couches (fermee avant que ce module n'existe).
Meme discipline que `apps.mrp.tests.test_structural_constraints` :
`on_delete` (PROTECT/CASCADE/SET_NULL) des FK les plus significatives du
module, plus les `UniqueConstraint` posees.

RLS (isolation tenant) est hors-perimetre (couverte ailleurs)."""

from __future__ import annotations

import pytest
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.db.utils import IntegrityError

from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant
from apps.logistics.models import LogShipmentLeg, LogVehicleCost, LogVehicleDocument
from apps.logistics.tests.factories import (
    LogCustomsFileFactory,
    LogCustomsLineFactory,
    LogShipmentFactory,
    LogShipmentLegFactory,
    LogTripFactory,
    LogVehicleCostFactory,
    LogVehicleDocumentFactory,
    LogVehicleFactory,
)

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------
# on_delete=PROTECT
# --------------------------------------------------------------------------


def test_vehicle_cannot_be_deleted_while_referenced_by_a_trip() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        trip = LogTripFactory(tenant=tenant)
        vehicle = trip.vehicle

        with pytest.raises(ProtectedError):
            vehicle.delete()


def test_driver_cannot_be_deleted_while_referenced_by_a_trip() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        trip = LogTripFactory(tenant=tenant)
        driver = trip.driver

        with pytest.raises(ProtectedError):
            driver.delete()


def test_shipment_cannot_be_deleted_while_referenced_by_a_customs_file() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        customs_file = LogCustomsFileFactory(tenant=tenant)
        shipment = customs_file.shipment

        with pytest.raises(ProtectedError):
            shipment.delete()


def test_hs_code_cannot_be_deleted_while_referenced_by_a_customs_line() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        line = LogCustomsLineFactory(tenant=tenant)
        hs_code = line.hs_code

        with pytest.raises(ProtectedError):
            hs_code.delete()


# --------------------------------------------------------------------------
# on_delete=CASCADE
# --------------------------------------------------------------------------


def test_deleting_a_vehicle_cascades_to_its_documents_and_costs() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        vehicle = LogVehicleFactory(tenant=tenant)
        document = LogVehicleDocumentFactory(tenant=tenant, vehicle=vehicle)
        cost = LogVehicleCostFactory(tenant=tenant, vehicle=vehicle)
        document_id, cost_id = document.id, cost.id

        vehicle.delete()

        assert not LogVehicleDocument.objects.filter(pk=document_id).exists()
        assert not LogVehicleCost.objects.filter(pk=cost_id).exists()


def test_deleting_a_shipment_cascades_to_its_legs() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        leg = LogShipmentLegFactory(tenant=tenant)
        shipment = leg.shipment
        leg_id = leg.id

        shipment.delete()

        assert not LogShipmentLeg.objects.filter(pk=leg_id).exists()


# --------------------------------------------------------------------------
# UniqueConstraint
# --------------------------------------------------------------------------


def test_vehicle_plate_number_unique_per_tenant() -> None:
    """`LogVehicle.Meta.constraints` : `uniq_log_vehicle_plate_number`."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        LogVehicleFactory(tenant=tenant, plate_number="4321-TAA")

        with pytest.raises(IntegrityError), transaction.atomic():
            LogVehicleFactory(tenant=tenant, plate_number="4321-TAA")


def test_shipment_leg_sequence_unique_per_shipment() -> None:
    """`LogShipmentLeg.Meta.constraints` : `uniq_log_shipment_leg_sequence`."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        shipment = LogShipmentFactory(tenant=tenant)
        LogShipmentLegFactory(tenant=tenant, shipment=shipment, sequence=1)

        with pytest.raises(IntegrityError), transaction.atomic():
            LogShipmentLegFactory(tenant=tenant, shipment=shipment, sequence=1)
