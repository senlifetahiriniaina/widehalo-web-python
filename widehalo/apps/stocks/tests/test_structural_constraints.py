"""T2 (couches 4-5 du CDC, §8) : contraintes structurelles/d'interdependance
au niveau base pour `stocks` — comble le trou laisse par la premiere passe
de verification des 14 couches (fermee avant que ce module n'existe). Meme
discipline que `apps.mrp.tests.test_structural_constraints` : `on_delete`
(PROTECT/CASCADE/SET_NULL) des FK les plus significatives du module, plus
les deux `UniqueConstraint` documentees comme structurantes
(`uniq_stk_lot_variant_name`, `uniq_stk_quant_variant_location_lot` avec
`nulls_distinct=False`).

RLS (isolation tenant) est hors-perimetre (couverte ailleurs)."""

from __future__ import annotations

import uuid

import pytest
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.db.utils import IntegrityError

from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant
from apps.stocks.tests.factories import (
    StkInventoryFactory,
    StkLocationFactory,
    StkLotFactory,
    StkMoveFactory,
    StkNegativeStockExceptionFactory,
    StkQuantFactory,
    StkValuationLayerFactory,
)

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------
# on_delete=PROTECT
# --------------------------------------------------------------------------


def test_location_cannot_be_deleted_while_referenced_by_a_quant() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        quant = StkQuantFactory(tenant=tenant)
        location = quant.location

        with pytest.raises(ProtectedError):
            location.delete()


def test_location_cannot_be_deleted_while_referenced_by_a_move() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        move = StkMoveFactory(tenant=tenant)
        location_from = move.location_from

        with pytest.raises(ProtectedError):
            location_from.delete()


def test_warehouse_cannot_be_deleted_while_referenced_by_an_inventory() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        inventory = StkInventoryFactory(tenant=tenant)
        warehouse = inventory.warehouse

        with pytest.raises(ProtectedError):
            warehouse.delete()


def test_move_cannot_be_deleted_while_referenced_by_a_valuation_layer() -> None:
    """`StkValuationLayer.move` est PROTECT : la valorisation historique
    d'un mouvement ne doit jamais pouvoir etre orpheline silencieusement."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        layer = StkValuationLayerFactory(tenant=tenant)
        move = layer.move

        with pytest.raises(ProtectedError):
            move.delete()


def test_authorized_by_cannot_be_deleted_while_referenced_by_a_negative_stock_exception() -> None:
    """`StkNegativeStockException.authorized_by` est PROTECT (jamais
    SET_NULL) : QUI a autorise un depassement en negatif reste toujours
    tracable."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        exception = StkNegativeStockExceptionFactory(tenant=tenant)
        authorized_by = exception.authorized_by

        with pytest.raises(ProtectedError):
            authorized_by.delete()


# --------------------------------------------------------------------------
# on_delete=SET_NULL
# --------------------------------------------------------------------------


def test_deleting_a_lot_nullifies_the_quant() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        lot = StkLotFactory(tenant=tenant)
        quant = StkQuantFactory(tenant=tenant, lot=lot)

        lot.delete()
        quant.refresh_from_db()

        assert quant.lot_id is None


def test_deleting_a_lot_nullifies_the_move() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        lot = StkLotFactory(tenant=tenant)
        move = StkMoveFactory(tenant=tenant, lot=lot)

        lot.delete()
        move.refresh_from_db()

        assert move.lot_id is None


# --------------------------------------------------------------------------
# UniqueConstraint
# --------------------------------------------------------------------------


def test_lot_unique_per_tenant_variant_and_name() -> None:
    """`StkLot.Meta.constraints` : `uniq_stk_lot_variant_name`."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        StkLotFactory(tenant=tenant, variant_id=variant_id, name="LOT-DUP")

        with pytest.raises(IntegrityError), transaction.atomic():
            StkLotFactory(tenant=tenant, variant_id=variant_id, name="LOT-DUP")


def test_quant_unique_per_variant_location_and_lot() -> None:
    """`StkQuant.Meta.constraints` : `uniq_stk_quant_variant_location_lot`."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        location = StkLocationFactory(tenant=tenant)
        variant_id = uuid.uuid4()
        StkQuantFactory(tenant=tenant, variant_id=variant_id, location=location)

        with pytest.raises(IntegrityError), transaction.atomic():
            StkQuantFactory(tenant=tenant, variant_id=variant_id, location=location)


def test_quant_unique_constraint_treats_null_lot_as_equal_across_rows() -> None:
    """`nulls_distinct=False` : deux quants "sans lot" pour le meme couple
    (variant, emplacement) sont bien traites comme le MEME enregistrement
    au regard de la contrainte, pas comme deux NULL distincts — c'est
    exactement la raison d'etre documentee de ce parametre (cf. docstring du
    modele)."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        location = StkLocationFactory(tenant=tenant)
        variant_id = uuid.uuid4()
        StkQuantFactory(tenant=tenant, variant_id=variant_id, location=location, lot=None)

        with pytest.raises(IntegrityError), transaction.atomic():
            StkQuantFactory(tenant=tenant, variant_id=variant_id, location=location, lot=None)
