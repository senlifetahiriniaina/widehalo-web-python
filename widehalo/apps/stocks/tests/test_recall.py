"""A3 (L4 Agro, cf. docs/planning/2026-refonte-ux-sprints.md §5) : rappel
produit (RG-STK-11) — `services/recall.py` + garde hold/release dans
`services/moves.create_move` (`StkLot.is_held`)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLocation, StkLot, StkMove, StkQualityState, StkRecall
from apps.stocks.services.genealogy import record_consumption
from apps.stocks.services.moves import create_move, validate_move
from apps.stocks.services.quality import set_quality_state
from apps.stocks.services.recall import close_recall, declare_recall
from apps.stocks.services.warehouses import create_location, create_warehouse

pytestmark = pytest.mark.django_db


def _internal_and_supplier(tenant):
    warehouse = create_warehouse(tenant=tenant, code="WH-R", name="Entrepot rappel")
    internal = create_location(
        tenant=tenant, warehouse=warehouse, code="INT", name="Interne",
        type=StkLocation.TYPE_INTERNE,
    )
    supplier = create_location(
        tenant=tenant, warehouse=warehouse, code="FRS", name="Fournisseur",
        type=StkLocation.TYPE_FOURNISSEUR,
    )
    client = create_location(
        tenant=tenant, warehouse=warehouse, code="CLI", name="Client", type=StkLocation.TYPE_CLIENT
    )
    return warehouse, internal, supplier, client


def test_lot_is_held_after_quarantine_state() -> None:
    tenant = Tenant.objects.create(code="RCL-1", name="Recall Tenant 1")
    with use_tenant(tenant.id):
        lot = StkLot.objects.create(tenant=tenant, variant_id=uuid.uuid4(), name="LOT-HOLD-1")
        assert lot.is_held() is False

        set_quality_state(tenant=tenant, lot=lot, state=StkQualityState.STATE_EN_QUARANTAINE)
        assert lot.is_held() is True

        set_quality_state(tenant=tenant, lot=lot, state=StkQualityState.STATE_CONFORME)
        assert lot.is_held() is False


def test_create_move_refuses_to_move_a_held_lot_out() -> None:
    tenant = Tenant.objects.create(code="RCL-2", name="Recall Tenant 2")
    with use_tenant(tenant.id):
        _wh, internal, supplier, client = _internal_and_supplier(tenant)
        variant_id = uuid.uuid4()
        lot = StkLot.objects.create(tenant=tenant, variant_id=variant_id, name="LOT-HOLD-2")
        reception = create_move(
            tenant=tenant, variant_id=variant_id, qty=Decimal("10"), uom="kg",
            location_from=supplier, location_to=internal, date=dt.date.today(),
            move_type=StkMove.TYPE_RECEPTION, lot=lot,
        )
        validate_move(reception)

        set_quality_state(tenant=tenant, lot=lot, state=StkQualityState.STATE_EN_QUARANTAINE)

        with pytest.raises(ValidationError):
            create_move(
                tenant=tenant, variant_id=variant_id, qty=Decimal("5"), uom="kg",
                location_from=internal, location_to=client, date=dt.date.today(),
                move_type=StkMove.TYPE_LIVRAISON, lot=lot,
            )


def test_create_move_still_allows_relocating_a_held_lot_to_quarantine() -> None:
    tenant = Tenant.objects.create(code="RCL-3", name="Recall Tenant 3")
    with use_tenant(tenant.id):
        _wh, internal, supplier, _client = _internal_and_supplier(tenant)
        quarantine = create_location(
            tenant=tenant, warehouse=internal.warehouse, code="QUA", name="Quarantaine",
            type=StkLocation.TYPE_INVENTAIRE,
        )
        variant_id = uuid.uuid4()
        lot = StkLot.objects.create(tenant=tenant, variant_id=variant_id, name="LOT-HOLD-3")
        reception = create_move(
            tenant=tenant, variant_id=variant_id, qty=Decimal("10"), uom="kg",
            location_from=supplier, location_to=internal, date=dt.date.today(),
            move_type=StkMove.TYPE_RECEPTION, lot=lot,
        )
        validate_move(reception)
        set_quality_state(tenant=tenant, lot=lot, state=StkQualityState.STATE_EN_QUARANTAINE)

        move = create_move(
            tenant=tenant, variant_id=variant_id, qty=Decimal("10"), uom="kg",
            location_from=internal, location_to=quarantine, date=dt.date.today(),
            move_type=StkMove.TYPE_REBUT, lot=lot,
        )
        validate_move(move)
        assert move.state == StkMove.STATE_DONE


def test_create_move_allows_relocating_a_held_lot_to_a_type_interne_quarantine() -> None:
    """Régression : `services.quality`'s propre docstring documente
    `TYPE_INTERNE` comme choix valide de `quarantine_or_scrap_location`
    pour un `defaut_majeur` (pas seulement `TYPE_REBUT`/`TYPE_INVENTAIRE`)
    — la garde RG-STK-11 doit donc aussi exempter un mouvement
    `move_type=TYPE_REBUT` vers un `TYPE_INTERNE`, pas seulement vers un
    emplacement de type quarantaine/rebut."""
    tenant = Tenant.objects.create(code="RCL-3B", name="Recall Tenant 3B")
    with use_tenant(tenant.id):
        _wh, internal, supplier, _client = _internal_and_supplier(tenant)
        dedicated_quarantine = create_location(
            tenant=tenant, warehouse=internal.warehouse, code="QUA-INT",
            name="Quarantaine (zone interne dédiée)", type=StkLocation.TYPE_INTERNE,
        )
        variant_id = uuid.uuid4()
        lot = StkLot.objects.create(tenant=tenant, variant_id=variant_id, name="LOT-HOLD-3B")
        reception = create_move(
            tenant=tenant, variant_id=variant_id, qty=Decimal("10"), uom="kg",
            location_from=supplier, location_to=internal, date=dt.date.today(),
            move_type=StkMove.TYPE_RECEPTION, lot=lot,
        )
        validate_move(reception)
        set_quality_state(tenant=tenant, lot=lot, state=StkQualityState.STATE_DEFAUT_MAJEUR)

        move = create_move(
            tenant=tenant, variant_id=variant_id, qty=Decimal("10"), uom="kg",
            location_from=internal, location_to=dedicated_quarantine, date=dt.date.today(),
            move_type=StkMove.TYPE_REBUT, lot=lot,
        )
        validate_move(move)
        assert move.state == StkMove.STATE_DONE


def test_declare_recall_holds_lot_and_all_descendants_and_captures_client_exposure() -> None:
    tenant = Tenant.objects.create(code="RCL-4", name="Recall Tenant 4")
    user = UserFactory()
    with use_tenant(tenant.id):
        _wh, internal, supplier, client = _internal_and_supplier(tenant)
        raw_variant = uuid.uuid4()
        finished_variant = uuid.uuid4()
        raw_lot = StkLot.objects.create(tenant=tenant, variant_id=raw_variant, name="MP-RAPPEL-1")
        finished_lot = StkLot.objects.create(
            tenant=tenant, variant_id=finished_variant, name="PF-RAPPEL-1"
        )
        record_consumption(
            tenant=tenant, parent_lot=raw_lot, child_lot=finished_lot, qty=Decimal("20"),
            source_document="MRP-OF-2026-0099",
        )
        reception = create_move(
            tenant=tenant, variant_id=finished_variant, qty=Decimal("20"), uom="kg",
            location_from=supplier, location_to=internal, date=dt.date.today(),
            move_type=StkMove.TYPE_RECEPTION, lot=finished_lot,
        )
        validate_move(reception)
        delivery = create_move(
            tenant=tenant, variant_id=finished_variant, qty=Decimal("5"), uom="kg",
            location_from=internal, location_to=client, date=dt.date.today(),
            move_type=StkMove.TYPE_LIVRAISON, source_document="CMD-CLIENT-42", lot=finished_lot,
        )
        validate_move(delivery)

        recall = declare_recall(lot=raw_lot, reason="Contamination suspectée", initiated_by=user)

        assert recall.state == StkRecall.STATE_OPEN
        assert set(recall.impacted_lot_names) == {"MP-RAPPEL-1", "PF-RAPPEL-1"}
        assert recall.client_exposures[0]["source_document"] == "CMD-CLIENT-42"
        assert raw_lot.is_held() is True
        assert finished_lot.is_held() is True


def test_close_recall_sets_state_and_metadata_without_releasing_lots() -> None:
    tenant = Tenant.objects.create(code="RCL-5", name="Recall Tenant 5")
    user = UserFactory()
    with use_tenant(tenant.id):
        lot = StkLot.objects.create(tenant=tenant, variant_id=uuid.uuid4(), name="LOT-CLOSE-1")
        recall = declare_recall(lot=lot, reason="Test", initiated_by=user)

        close_recall(recall, closed_by=user)

        recall.refresh_from_db()
        assert recall.state == StkRecall.STATE_CLOSED
        assert recall.closed_by == user
        assert recall.closed_at is not None
        assert lot.is_held() is True  # clore le dossier ne libère pas le lot automatiquement
