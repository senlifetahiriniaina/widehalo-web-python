"""STK-9 (Phase 3 §7.3, sprint A6, mode dégradé terrain) : `client_uuid`
comme clef d'idempotence sur `sync_scan_reception_line` — même discipline
que `apps.pos.services.orders.sync_order` (`apps/pos/tests/
test_offline_sync.py`, patron directement repris ici) : un rejeu du même
`client_uuid` (perte de réseau + nouvel essai) ne doit jamais créer un
second `StkMove`, et un rejet ne doit laisser aucun mouvement partiel.
Chaque tentative est journalisée via `AuditLog` (pas un modèle `stocks`
dédié, cf. docstring `services.scan`)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.catalog.tests.factories import ProductVariantFactory
from apps.core.models.audit import AuditLog
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLocation, StkMove
from apps.stocks.services import scan
from apps.stocks.services.scan import sync_scan_reception_line
from apps.stocks.services.warehouses import create_location, create_warehouse

pytestmark = pytest.mark.django_db


@pytest.fixture
def scan_setup():
    tenant = Tenant.objects.create(code="STK-SCAN", name="Stocks Scan Tenant")
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-SCAN", name="Entrepot scan")
        supplier = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="FRS",
            name="Fournisseur",
            type=StkLocation.TYPE_FOURNISSEUR,
        )
        internal = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="A1",
            name="Rayon A1",
            type=StkLocation.TYPE_INTERNE,
        )
        variant = ProductVariantFactory(tenant=tenant, ean13="1234567890128")
        return tenant, supplier, internal, variant


def _line_kwargs(client_uuid, *, ean13, location_from, location_to):
    return {
        "client_uuid": client_uuid,
        "location_from": location_from,
        "location_to": location_to,
        "ean13": ean13,
        "qty": Decimal(1),
        "uom": "pc",
        "date": dt.date(2026, 3, 1),
    }


def _audit_actions(client_uuid: uuid.UUID) -> list[str]:
    return [
        log.action
        for log in AuditLog.objects.filter(
            action__in=[scan.ACTION_ACCEPTED, scan.ACTION_DUPLICATE, scan.ACTION_REJECTED]
        )
        if log.metadata.get("client_uuid") == str(client_uuid)
    ]


def test_replaying_the_same_client_uuid_never_creates_a_second_move(scan_setup) -> None:
    tenant, supplier, internal, variant = scan_setup
    client_uuid = uuid.uuid4()
    with use_tenant(tenant.id):
        kwargs = _line_kwargs(
            client_uuid, ean13=variant.ean13, location_from=supplier, location_to=internal
        )

        move1, outcome1 = sync_scan_reception_line(tenant, **kwargs)
        assert outcome1 == scan.OUTCOME_ACCEPTED
        assert move1 is not None
        assert move1.state == StkMove.STATE_DONE
        assert move1.move_type == StkMove.TYPE_RECEPTION
        assert move1.client_uuid == client_uuid

        move2, outcome2 = sync_scan_reception_line(tenant, **kwargs)
        assert outcome2 == scan.OUTCOME_DUPLICATE
        assert move2 is not None
        assert move2.id == move1.id

        assert StkMove.objects.filter(client_uuid=client_uuid).count() == 1
        actions = _audit_actions(client_uuid)
        assert len(actions) == 2
        assert set(actions) == {scan.ACTION_ACCEPTED, scan.ACTION_DUPLICATE}


def test_unknown_ean13_is_rejected_and_leaves_no_partial_move(scan_setup) -> None:
    tenant, supplier, internal, _variant = scan_setup
    client_uuid = uuid.uuid4()
    with use_tenant(tenant.id):
        kwargs = _line_kwargs(
            client_uuid,
            ean13="0000000000000",
            location_from=supplier,
            location_to=internal,
        )

        with pytest.raises(ValidationError):
            sync_scan_reception_line(tenant, **kwargs)

        assert not StkMove.objects.filter(client_uuid=client_uuid).exists()
        log = AuditLog.objects.get(action=scan.ACTION_REJECTED)
        assert log.metadata["client_uuid"] == str(client_uuid)
        assert "0000000000000" in log.metadata["detail"]
        assert log.content_type is None
