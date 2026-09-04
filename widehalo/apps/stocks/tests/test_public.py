"""Tests du contrat public de `stocks` (`apps/stocks/services/public.py`) —
seule surface que `logistics` (LOG5, RG-LOG-7) et, depuis ce chantier de
durcissement retroactif, `sales`/`purchase` ont le droit d'importer.
Couvre les trois gaps exposes : `apply_landed_cost_to_valuation` (deja
construit LOG5, jusqu'ici seulement exerce indirectement via
`apps.logistics.services.customs.close_customs_file`), et les deux
nouveaux gaps `check_and_reserve_stock`/`get_available_stock_qty`."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.catalog.models import ProductTemplate, ProductVariant, UnitOfMeasure
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.stocks.models import (
    StkLocation,
    StkLot,
    StkPicking,
    StkQualityState,
    StkQuant,
    StkReservation,
)
from apps.stocks.services.public import (
    QUALITY_STATE_CONFORME,
    QUALITY_STATE_QUARANTINE,
    apply_landed_cost_to_valuation,
    check_and_reserve_stock,
    deliver_reserved_stock,
    get_available_stock_qty,
    get_lot_certificate_document_id,
    get_or_create_lot,
    get_variant_unit_cost,
    receive_pos_return,
    receive_purchase_line,
    sell_from_stock,
    set_quality_state,
)
from apps.stocks.tests.factories import (
    StkLocationFactory,
    StkLotFactory,
    StkMoveFactory,
    StkQuantFactory,
    StkValuationLayerFactory,
    StkWarehouseFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    t = Tenant.objects.create(code="STK-PUB", name="Stocks Public Tenant")
    with use_tenant(t.id):
        yield t


# ---------------------------------------------------------------------------
# apply_landed_cost_to_valuation (deja construit LOG5) — cf. module docstring.
# ---------------------------------------------------------------------------


def test_apply_landed_cost_to_valuation_prorates_across_active_layers(tenant) -> None:
    variant_id = uuid.uuid4()
    layer_a = StkValuationLayerFactory(
        tenant=tenant,
        variant_id=variant_id,
        qty=Decimal(30),
        remaining_qty=Decimal(30),
        value_mga=Decimal("300000"),
        remaining_value_mga=Decimal("300000"),
    )
    layer_b = StkValuationLayerFactory(
        tenant=tenant,
        variant_id=variant_id,
        qty=Decimal(10),
        remaining_qty=Decimal(10),
        value_mga=Decimal("100000"),
        remaining_value_mga=Decimal("100000"),
    )

    result = apply_landed_cost_to_valuation(variant_id, additional_cost_mga=Decimal("40000"))

    assert result is True
    layer_a.refresh_from_db()
    layer_b.refresh_from_db()
    # Prorata sur remaining_qty : 30/40 et 10/40 de 40000 -> 30000 et 10000.
    assert layer_a.remaining_value_mga == Decimal("330000")
    assert layer_b.remaining_value_mga == Decimal("110000")


def test_apply_landed_cost_to_valuation_returns_false_without_active_layers(tenant) -> None:
    result = apply_landed_cost_to_valuation(uuid.uuid4(), additional_cost_mga=Decimal("10000"))
    assert result is False


# ---------------------------------------------------------------------------
# get_variant_unit_cost (Bloc C, C3) — coût CUMP courant en lecture pure.
# ---------------------------------------------------------------------------


def test_get_variant_unit_cost_is_weighted_average_across_active_layers(tenant) -> None:
    variant_id = uuid.uuid4()
    StkValuationLayerFactory(
        tenant=tenant,
        variant_id=variant_id,
        qty=Decimal(30),
        remaining_qty=Decimal(30),
        value_mga=Decimal("300000"),
        remaining_value_mga=Decimal("300000"),
    )
    StkValuationLayerFactory(
        tenant=tenant,
        variant_id=variant_id,
        qty=Decimal(10),
        remaining_qty=Decimal(10),
        value_mga=Decimal("100000"),
        remaining_value_mga=Decimal("100000"),
    )

    # (300000 + 100000) / (30 + 10) = 10000 Ar/unite.
    assert get_variant_unit_cost(tenant, variant_id) == Decimal(10000)


def test_get_variant_unit_cost_ignores_exhausted_layers(tenant) -> None:
    variant_id = uuid.uuid4()
    StkValuationLayerFactory(
        tenant=tenant,
        variant_id=variant_id,
        qty=Decimal(30),
        remaining_qty=Decimal(0),  # couche epuisee, exclue du calcul
        value_mga=Decimal("300000"),
        remaining_value_mga=Decimal("0"),
    )
    StkValuationLayerFactory(
        tenant=tenant,
        variant_id=variant_id,
        qty=Decimal(5),
        remaining_qty=Decimal(5),
        value_mga=Decimal("50000"),
        remaining_value_mga=Decimal("50000"),
    )

    assert get_variant_unit_cost(tenant, variant_id) == Decimal(10000)


def test_get_variant_unit_cost_is_none_without_any_active_layer(tenant) -> None:
    assert get_variant_unit_cost(tenant, uuid.uuid4()) is None


# ---------------------------------------------------------------------------
# check_and_reserve_stock — gap ajoute pour lever le stub RG-SAL-3 "sur stock".
# ---------------------------------------------------------------------------


def test_check_and_reserve_stock_reserves_a_single_sufficient_quant(tenant) -> None:
    variant_id = uuid.uuid4()
    location = StkLocationFactory(tenant=tenant)
    StkQuantFactory(
        tenant=tenant,
        variant_id=variant_id,
        location=location,
        qty=Decimal(20),
        qty_reserved=Decimal(5),
    )

    reservation_id = check_and_reserve_stock(
        tenant, variant_id=variant_id, qty=Decimal(10), date=dt.date(2026, 1, 15)
    )

    assert reservation_id is not None
    reservation = StkReservation.objects.get(id=reservation_id)
    assert reservation.qty == Decimal(10)
    assert reservation.state == StkReservation.STATE_ACTIVE


def test_check_and_reserve_stock_returns_none_without_a_single_sufficient_quant(tenant) -> None:
    """Deux quants de 10 chacun (20 au total) ne couvrent pas une demande
    de 15 a eux seuls — simplification assumee documentee, jamais un
    fractionnement de la reservation sur plusieurs quants."""
    variant_id = uuid.uuid4()
    StkQuantFactory(tenant=tenant, variant_id=variant_id, qty=Decimal(10))
    StkQuantFactory(tenant=tenant, variant_id=variant_id, qty=Decimal(10))

    reservation_id = check_and_reserve_stock(
        tenant, variant_id=variant_id, qty=Decimal(15), date=dt.date(2026, 1, 15)
    )

    assert reservation_id is None
    assert not StkReservation.objects.exists()


def test_check_and_reserve_stock_ignores_virtual_locations(tenant) -> None:
    variant_id = uuid.uuid4()
    virtual_location = StkLocationFactory(tenant=tenant, type=StkLocation.TYPE_FOURNISSEUR)
    StkQuantFactory(
        tenant=tenant, variant_id=variant_id, location=virtual_location, qty=Decimal(50)
    )

    reservation_id = check_and_reserve_stock(
        tenant, variant_id=variant_id, qty=Decimal(5), date=dt.date(2026, 1, 15)
    )

    assert reservation_id is None


def test_check_and_reserve_stock_records_source_object(tenant) -> None:
    variant_id = uuid.uuid4()
    StkQuantFactory(tenant=tenant, variant_id=variant_id, qty=Decimal(20))
    move = StkMoveFactory(tenant=tenant)

    reservation_id = check_and_reserve_stock(
        tenant, variant_id=variant_id, qty=Decimal(5), date=dt.date(2026, 1, 15), source_object=move
    )

    reservation = StkReservation.objects.get(id=reservation_id)
    assert reservation.object_id == str(move.pk)


# ---------------------------------------------------------------------------
# get_available_stock_qty — gap ajoute pour lever le stub RG-PUR-3.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# deliver_reserved_stock — correctif du gap sales.mark_delivered
# (docs/audit/2026-09-cahier-des-charges-v3-audit.md, §6/§8).
# ---------------------------------------------------------------------------


def test_deliver_reserved_stock_moves_qty_and_releases_reservation(tenant) -> None:
    variant_id = uuid.uuid4()
    warehouse = StkWarehouseFactory(tenant=tenant)
    internal_location = StkLocationFactory(tenant=tenant, warehouse=warehouse)
    client_location = StkLocationFactory(
        tenant=tenant, warehouse=warehouse, type=StkLocation.TYPE_CLIENT
    )
    quant = StkQuantFactory(
        tenant=tenant, variant_id=variant_id, location=internal_location, qty=Decimal(20)
    )
    reservation_id = check_and_reserve_stock(
        tenant, variant_id=variant_id, qty=Decimal(7), date=dt.date(2026, 1, 15)
    )
    assert reservation_id is not None

    picking_id = deliver_reserved_stock(
        tenant, reservation_id=reservation_id, date=dt.date(2026, 1, 16), source_document="CMD-1"
    )

    picking = StkPicking.objects.get(id=picking_id)
    assert picking.type == StkPicking.TYPE_SORTIE
    assert picking.state == StkPicking.STATE_DONE
    assert picking.location_from_id == internal_location.id
    assert picking.location_to_id == client_location.id
    assert picking.source_document == "CMD-1"

    quant.refresh_from_db()
    assert quant.qty == Decimal(13)  # 20 - 7 physiquement sorties
    assert quant.qty_reserved == Decimal(0)  # reservation liberee

    reservation = StkReservation.objects.get(id=reservation_id)
    assert reservation.state == StkReservation.STATE_RELEASED

    client_quant = StkQuant.objects.get(location=client_location, variant_id=variant_id)
    assert client_quant.qty == Decimal(7)  # double-entree RG-STK-1


def test_deliver_reserved_stock_raises_without_a_client_location(tenant) -> None:
    variant_id = uuid.uuid4()
    # Entrepot SANS emplacement virtuel "client" configure.
    internal_location = StkLocationFactory(tenant=tenant)
    StkQuantFactory(
        tenant=tenant, variant_id=variant_id, location=internal_location, qty=Decimal(20)
    )
    reservation_id = check_and_reserve_stock(
        tenant, variant_id=variant_id, qty=Decimal(5), date=dt.date(2026, 1, 15)
    )
    assert reservation_id is not None

    with pytest.raises(ValidationError):
        deliver_reserved_stock(tenant, reservation_id=reservation_id, date=dt.date(2026, 1, 16))

    # La reservation reste active — rien n'a ete perdu par l'echec.
    reservation = StkReservation.objects.get(id=reservation_id)
    assert reservation.state == StkReservation.STATE_ACTIVE


def test_get_available_stock_qty_aggregates_across_internal_quants(tenant) -> None:
    variant_id = uuid.uuid4()
    StkQuantFactory(tenant=tenant, variant_id=variant_id, qty=Decimal(20), qty_reserved=Decimal(5))
    StkQuantFactory(tenant=tenant, variant_id=variant_id, qty=Decimal(10), qty_reserved=Decimal(0))

    assert get_available_stock_qty(variant_id) == Decimal(25)


def test_get_available_stock_qty_is_zero_for_unknown_variant(tenant) -> None:
    assert get_available_stock_qty(uuid.uuid4()) == Decimal(0)


def test_sell_from_stock_moves_qty_without_any_prior_reservation(tenant) -> None:
    """Gap ajoute pour le module `pos` (POS distribution) : a la difference
    de `check_and_reserve_stock`/`deliver_reserved_stock`, aucune
    `StkReservation` n'est jamais creee sur ce chemin."""
    variant_id = uuid.uuid4()
    warehouse = StkWarehouseFactory(tenant=tenant)
    internal_location = StkLocationFactory(tenant=tenant, warehouse=warehouse)
    client_location = StkLocationFactory(
        tenant=tenant, warehouse=warehouse, type=StkLocation.TYPE_CLIENT
    )
    quant = StkQuantFactory(
        tenant=tenant, variant_id=variant_id, location=internal_location, qty=Decimal(20)
    )

    picking_id = sell_from_stock(
        tenant,
        variant_id=variant_id,
        qty=Decimal(6),
        warehouse_id=warehouse.id,
        date=dt.date(2026, 1, 15),
        source_document="TICKET-1",
    )

    picking = StkPicking.objects.get(id=picking_id)
    assert picking.type == StkPicking.TYPE_SORTIE
    assert picking.state == StkPicking.STATE_DONE
    assert picking.location_from_id == internal_location.id
    assert picking.location_to_id == client_location.id
    assert StkReservation.objects.count() == 0

    quant.refresh_from_db()
    assert quant.qty == Decimal(14)


def test_sell_from_stock_returns_none_without_enough_qty_or_a_client_location(tenant) -> None:
    variant_id = uuid.uuid4()
    warehouse = StkWarehouseFactory(tenant=tenant)
    internal_location = StkLocationFactory(tenant=tenant, warehouse=warehouse)
    StkQuantFactory(
        tenant=tenant, variant_id=variant_id, location=internal_location, qty=Decimal(3)
    )

    # Stock insuffisant.
    assert (
        sell_from_stock(
            tenant,
            variant_id=variant_id,
            qty=Decimal(5),
            warehouse_id=warehouse.id,
            date=dt.date(2026, 1, 15),
        )
        is None
    )
    # Aucun emplacement virtuel client configure pour cet entrepot.
    assert (
        sell_from_stock(
            tenant,
            variant_id=variant_id,
            qty=Decimal(1),
            warehouse_id=warehouse.id,
            date=dt.date(2026, 1, 15),
        )
        is None
    )


def test_receive_pos_return_puts_qty_back_into_the_first_internal_location(tenant) -> None:
    variant_id = uuid.uuid4()
    warehouse = StkWarehouseFactory(tenant=tenant)
    internal_location = StkLocationFactory(tenant=tenant, warehouse=warehouse)
    StkLocationFactory(tenant=tenant, warehouse=warehouse, type=StkLocation.TYPE_CLIENT)

    picking_id = receive_pos_return(
        tenant,
        variant_id=variant_id,
        qty=Decimal(2),
        warehouse_id=warehouse.id,
        date=dt.date(2026, 1, 16),
        source_document="AVOIR-1",
    )

    picking = StkPicking.objects.get(id=picking_id)
    assert picking.type == StkPicking.TYPE_ENTREE
    assert picking.state == StkPicking.STATE_DONE
    assert picking.location_to_id == internal_location.id

    quant = StkQuant.objects.get(location=internal_location, variant_id=variant_id)
    assert quant.qty == Decimal(2)


# ---------------------------------------------------------------------------
# set_quality_state (Bloc D, D1) — enveloppe cross-app, motif/identite
# obligatoires, resolution du lot par (tenant, variant_id, lot_name).
# ---------------------------------------------------------------------------


def test_set_quality_state_resolves_lot_and_blocks_it(tenant) -> None:
    user = User.objects.create_user(email="qs@example.com", password="Str0ngPassw0rd!23")
    lot = StkLotFactory(tenant=tenant, name="LOT-PUB-001")

    quality_state_id = set_quality_state(
        tenant,
        variant_id=lot.variant_id,
        lot_name=lot.name,
        state=QUALITY_STATE_QUARANTINE,
        description="Mesure hors limites",
        decided_by=user,
    )
    assert quality_state_id is not None

    lot.refresh_from_db()
    assert lot.is_held() is True
    quality_state = StkQualityState.objects.get(id=quality_state_id)
    assert quality_state.state == StkQualityState.STATE_EN_QUARANTAINE
    assert quality_state.description == "Mesure hors limites"
    assert quality_state.decided_by_id == user.id


def test_set_quality_state_returns_none_for_unknown_lot(tenant) -> None:
    user = User.objects.create_user(email="qs2@example.com", password="Str0ngPassw0rd!23")
    result = set_quality_state(
        tenant,
        variant_id=uuid.uuid4(),
        lot_name="INEXISTANT",
        state=QUALITY_STATE_QUARANTINE,
        description="Motif",
        decided_by=user,
    )
    assert result is None


def test_set_quality_state_conforme_releases_hold(tenant) -> None:
    user = User.objects.create_user(email="qs3@example.com", password="Str0ngPassw0rd!23")
    lot = StkLotFactory(tenant=tenant, name="LOT-PUB-002")
    set_quality_state(
        tenant,
        variant_id=lot.variant_id,
        lot_name=lot.name,
        state=QUALITY_STATE_QUARANTINE,
        description="Blocage initial",
        decided_by=user,
    )
    lot.refresh_from_db()
    assert lot.is_held() is True

    set_quality_state(
        tenant,
        variant_id=lot.variant_id,
        lot_name=lot.name,
        state=QUALITY_STATE_CONFORME,
        description="Analyse refaite, conforme",
        decided_by=user,
    )
    lot.refresh_from_db()
    assert lot.is_held() is False


# ---------------------------------------------------------------------------
# receive_purchase_line + certificat d'analyse (Bloc D, D2, QUA-8).
# ---------------------------------------------------------------------------


@pytest.fixture
def receiving_certificate_setup(tenant):
    uom = UnitOfMeasure.objects.create(
        tenant=tenant, code="KG-COA", name="Kilogramme", category=UnitOfMeasure.CATEGORY_WEIGHT
    )
    regulated_template = ProductTemplate.objects.create(
        tenant=tenant, name="Lait en poudre", base_uom=uom, requires_certificate_of_analysis=True
    )
    regulated_variant = ProductVariant.objects.create(tenant=tenant, template=regulated_template)
    plain_template = ProductTemplate.objects.create(
        tenant=tenant, name="Carton", base_uom=uom, requires_certificate_of_analysis=False
    )
    plain_variant = ProductVariant.objects.create(tenant=tenant, template=plain_template)
    warehouse = StkWarehouseFactory(tenant=tenant)
    StkLocationFactory(tenant=tenant, warehouse=warehouse, type=StkLocation.TYPE_INTERNE)
    return tenant, warehouse, regulated_variant, plain_variant


def test_receive_purchase_line_refuses_without_lot_when_certificate_required(
    receiving_certificate_setup,
) -> None:
    tenant, warehouse, regulated_variant, _plain_variant = receiving_certificate_setup
    with pytest.raises(ValidationError):
        receive_purchase_line(
            tenant=tenant,
            variant_id=regulated_variant.id,
            qty=Decimal(10),
            uom="KG-COA",
            warehouse_id=warehouse.id,
            date=dt.date(2026, 1, 10),
            source_document="PO-COA-1",
        )
    assert not StkLot.objects.filter(tenant=tenant, variant_id=regulated_variant.id).exists()


def test_receive_purchase_line_refuses_lot_without_certificate(receiving_certificate_setup) -> None:
    tenant, warehouse, regulated_variant, _plain_variant = receiving_certificate_setup
    with pytest.raises(ValidationError):
        receive_purchase_line(
            tenant=tenant,
            variant_id=regulated_variant.id,
            qty=Decimal(10),
            uom="KG-COA",
            warehouse_id=warehouse.id,
            date=dt.date(2026, 1, 10),
            source_document="PO-COA-2",
            lot_name="LOT-COA-001",
        )


def test_receive_purchase_line_accepts_lot_with_certificate(receiving_certificate_setup) -> None:
    tenant, warehouse, regulated_variant, _plain_variant = receiving_certificate_setup
    certificate_id = uuid.uuid4()
    move_id = receive_purchase_line(
        tenant=tenant,
        variant_id=regulated_variant.id,
        qty=Decimal(10),
        uom="KG-COA",
        warehouse_id=warehouse.id,
        date=dt.date(2026, 1, 10),
        source_document="PO-COA-3",
        lot_name="LOT-COA-002",
        certificate_document_id=certificate_id,
    )
    assert move_id is not None
    lot = StkLot.objects.get(tenant=tenant, variant_id=regulated_variant.id, name="LOT-COA-002")
    assert lot.certificate_document_id == certificate_id
    assert (
        get_lot_certificate_document_id(
            tenant=tenant, variant_id=regulated_variant.id, name="LOT-COA-002"
        )
        == certificate_id
    )


def test_receive_purchase_line_accepts_without_lot_when_certificate_not_required(
    receiving_certificate_setup,
) -> None:
    """Non-régression : un article qui n'exige pas de certificat continue
    de se réceptionner sans lot, exactement comme avant ce chantier."""
    tenant, warehouse, _regulated_variant, plain_variant = receiving_certificate_setup
    move_id = receive_purchase_line(
        tenant=tenant,
        variant_id=plain_variant.id,
        qty=Decimal(10),
        uom="KG-COA",
        warehouse_id=warehouse.id,
        date=dt.date(2026, 1, 10),
        source_document="PO-COA-4",
    )
    assert move_id is not None
    assert not StkLot.objects.filter(tenant=tenant, variant_id=plain_variant.id).exists()


def test_get_or_create_lot_applies_certificate_only_at_creation(tenant) -> None:
    variant_id = uuid.uuid4()
    first_certificate = uuid.uuid4()
    lot_id = get_or_create_lot(
        tenant=tenant,
        variant_id=variant_id,
        name="LOT-CREATE-ONCE",
        certificate_document_id=first_certificate,
    )
    lot = StkLot.objects.get(id=lot_id)
    assert lot.certificate_document_id == first_certificate

    second_certificate = uuid.uuid4()
    same_lot_id = get_or_create_lot(
        tenant=tenant,
        variant_id=variant_id,
        name="LOT-CREATE-ONCE",
        certificate_document_id=second_certificate,
    )
    assert same_lot_id == lot_id
    lot.refresh_from_db()
    assert lot.certificate_document_id == first_certificate  # inchange, jamais mis a jour


def test_get_lot_certificate_document_id_is_none_for_unknown_lot(tenant) -> None:
    assert (
        get_lot_certificate_document_id(tenant=tenant, variant_id=uuid.uuid4(), name="INEXISTANT")
        is None
    )
