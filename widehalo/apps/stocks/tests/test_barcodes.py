"""STK-BC1 (codes-barres/QR, ST7 du sous-sequencement `stocks` — cf.
plan) : generation de valeur deterministe, rendu QR PNG, unicite
applicative par tenant sur `StkLocation`/`StkLot`, lookup inverse."""

from __future__ import annotations

import uuid

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLot
from apps.stocks.services.barcodes import (
    generate_barcode_value,
    generate_qr_code_png,
    lookup_by_barcode,
    lookup_lot_by_barcode,
    set_location_barcode,
    set_lot_barcode,
)
from apps.stocks.services.warehouses import create_location, create_warehouse

pytestmark = pytest.mark.django_db

_PNG_MAGIC = b"\x89PNG"


@pytest.fixture
def barcode_setup():
    tenant = Tenant.objects.create(code="STK-BC-T", name="Stocks Barcode Tenant")
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-01", name="Entrepot principal")
        location_a = create_location(tenant=tenant, warehouse=warehouse, code="A1", name="Rayon A1")
        location_b = create_location(tenant=tenant, warehouse=warehouse, code="A2", name="Rayon A2")
        lot_a = StkLot.objects.create(tenant=tenant, variant_id=uuid.uuid4(), name="LOT-A")
        lot_b = StkLot.objects.create(tenant=tenant, variant_id=uuid.uuid4(), name="LOT-B")
    return tenant, location_a, location_b, lot_a, lot_b


def test_generate_barcode_value_is_deterministic() -> None:
    value_1 = generate_barcode_value(prefix="LOC", identifier="a1")
    value_2 = generate_barcode_value(prefix="LOC", identifier="a1")
    assert value_1 == value_2 == "LOC-A1"


def test_generate_barcode_value_differs_by_identifier() -> None:
    assert generate_barcode_value(prefix="LOC", identifier="a1") != generate_barcode_value(
        prefix="LOC", identifier="a2"
    )


def test_generate_qr_code_png_produces_valid_png_bytes() -> None:
    png_bytes = generate_qr_code_png("LOC-A1")
    assert isinstance(png_bytes, bytes)
    assert png_bytes[:4] == _PNG_MAGIC
    assert len(png_bytes) > 100


def test_set_location_barcode_auto_generates_when_omitted(barcode_setup) -> None:
    tenant, location_a, _location_b, _lot_a, _lot_b = barcode_setup
    with use_tenant(tenant.id):
        updated = set_location_barcode(location_a)
        assert updated.barcode == f"LOC-{location_a.code.upper()}"


def test_set_location_barcode_accepts_explicit_value(barcode_setup) -> None:
    tenant, location_a, _location_b, _lot_a, _lot_b = barcode_setup
    with use_tenant(tenant.id):
        updated = set_location_barcode(location_a, value="CUSTOM-CODE-1")
        assert updated.barcode == "CUSTOM-CODE-1"


def test_set_location_barcode_refuses_duplicate_active_barcode(barcode_setup) -> None:
    tenant, location_a, location_b, _lot_a, _lot_b = barcode_setup
    with use_tenant(tenant.id):
        set_location_barcode(location_a, value="DUP-1")
        with pytest.raises(ValidationError):
            set_location_barcode(location_b, value="DUP-1")


def test_set_location_barcode_allows_reuse_after_soft_delete(barcode_setup) -> None:
    tenant, location_a, location_b, _lot_a, _lot_b = barcode_setup
    with use_tenant(tenant.id):
        set_location_barcode(location_a, value="DUP-2")
        location_a.soft_delete()
        # Refuse toujours de reappliquer une meme valeur au meme emplacement
        # qui l'a deja (idempotence non testee ici) mais un AUTRE
        # emplacement peut desormais reutiliser cette valeur, l'ancien
        # porteur n'etant plus actif.
        updated = set_location_barcode(location_b, value="DUP-2")
        assert updated.barcode == "DUP-2"


def test_lookup_by_barcode_round_trip(barcode_setup) -> None:
    tenant, location_a, _location_b, _lot_a, _lot_b = barcode_setup
    with use_tenant(tenant.id):
        set_location_barcode(location_a, value="ROUNDTRIP-1")
        found = lookup_by_barcode(tenant, "ROUNDTRIP-1")
        assert found is not None
        assert found.id == location_a.id


def test_lookup_by_barcode_returns_none_when_not_found(barcode_setup) -> None:
    tenant, *_rest = barcode_setup
    with use_tenant(tenant.id):
        assert lookup_by_barcode(tenant, "DOES-NOT-EXIST") is None


def test_set_lot_barcode_auto_generates_when_omitted(barcode_setup) -> None:
    tenant, _location_a, _location_b, lot_a, _lot_b = barcode_setup
    with use_tenant(tenant.id):
        updated = set_lot_barcode(lot_a)
        assert updated.barcode == f"LOT-{lot_a.name.upper()}"


def test_set_lot_barcode_refuses_duplicate_active_barcode(barcode_setup) -> None:
    tenant, _location_a, _location_b, lot_a, lot_b = barcode_setup
    with use_tenant(tenant.id):
        set_lot_barcode(lot_a, value="DUP-LOT-1")
        with pytest.raises(ValidationError):
            set_lot_barcode(lot_b, value="DUP-LOT-1")


def test_lookup_lot_by_barcode_round_trip(barcode_setup) -> None:
    tenant, _location_a, _location_b, lot_a, _lot_b = barcode_setup
    with use_tenant(tenant.id):
        set_lot_barcode(lot_a, value="LOT-ROUNDTRIP-1")
        found = lookup_lot_by_barcode(tenant, "LOT-ROUNDTRIP-1")
        assert found is not None
        assert found.id == lot_a.id


def test_lookup_lot_by_barcode_returns_none_when_not_found(barcode_setup) -> None:
    tenant, *_rest = barcode_setup
    with use_tenant(tenant.id):
        assert lookup_lot_by_barcode(tenant, "DOES-NOT-EXIST") is None
