"""RG-STK-9 (inventaire physique + ecriture comptable auto, ST5 du
sous-sequencement `stocks` — cf. plan) : cycle de vie complet
`draft -> in_progress -> validated`, comptage avec/sans ecart au-dela du
seuil, generation des mouvements d'ajustement REELS et de l'ecriture
comptable de regularisation."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounting.models import AccAccount, AccJournal
from apps.accounting.tests.factories import AccAccountFactory, AccJournalFactory, AccPeriodFactory
from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkInventory, StkLocation, StkMove
from apps.stocks.services.inventory import (
    DEFAULT_VARIANCE_THRESHOLD_PCT,
    add_inventory_line,
    cancel_inventory,
    create_inventory,
    record_count,
    start_inventory,
    validate_inventory,
)
from apps.stocks.services.moves import create_move, validate_move
from apps.stocks.services.quants import get_quant
from apps.stocks.services.warehouses import create_location, create_warehouse

pytestmark = pytest.mark.django_db


@pytest.fixture
def inventory_setup():
    tenant = Tenant.objects.create(code="STK-INV-T", name="Stocks Inventory Tenant")
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-01", name="Entrepot principal")
        location = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="A1",
            name="Rayon A1",
            type=StkLocation.TYPE_INTERNE,
        )
        supplier = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="FRS",
            name="Fournisseur",
            type=StkLocation.TYPE_FOURNISSEUR,
        )
        user = UserFactory()
        return tenant, warehouse, location, supplier, user


def _receive_stock(tenant, supplier, location, variant_id, qty, unit_cost=Decimal("1000")):
    move = create_move(
        tenant=tenant,
        variant_id=variant_id,
        qty=qty,
        uom="pc",
        location_from=supplier,
        location_to=location,
        date=dt.date(2026, 1, 1),
        move_type=StkMove.TYPE_RECEPTION,
        unit_cost_mga=unit_cost,
    )
    return validate_move(move)


def _accounting_config(tenant):
    AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_STOCK)
    AccPeriodFactory(tenant=tenant, date_start=dt.date(2026, 1, 1), date_end=dt.date(2026, 12, 31))
    AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_STOCK)
    AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_EXPENSE)


def test_full_flow_positive_variance_creates_move_and_accounting_entry(inventory_setup) -> None:
    tenant, warehouse, location, supplier, user = inventory_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _receive_stock(tenant, supplier, location, variant_id, Decimal("100"))
        _accounting_config(tenant)

        inventory = create_inventory(
            tenant=tenant, warehouse=warehouse, date=dt.date(2026, 1, 15), type="ponctuel"
        )
        line = add_inventory_line(inventory, variant_id=variant_id, location=location)
        assert line.qty_theoretical == Decimal("100.0000")

        start_inventory(inventory)
        inventory.refresh_from_db()
        assert inventory.state == StkInventory.STATE_IN_PROGRESS

        record_count(line, qty_counted=Decimal("105"), counted_by=user)
        line.refresh_from_db()
        assert line.difference == Decimal("5.0000")

        validate_inventory(inventory, validated_by=user)
        inventory.refresh_from_db()
        assert inventory.state == StkInventory.STATE_VALIDATED
        assert inventory.validated_by_id == user.id

        quant = get_quant(variant_id, location)
        assert quant is not None
        assert quant.qty == Decimal("105.0000")

        adjustment_move = StkMove.objects.get(
            variant_id=variant_id, move_type=StkMove.TYPE_AJUSTEMENT
        )
        assert adjustment_move.state == StkMove.STATE_DONE
        assert adjustment_move.location_to_id == location.id
        assert adjustment_move.qty == Decimal("5.0000")


def test_full_flow_negative_variance_consumes_stock(inventory_setup) -> None:
    tenant, warehouse, location, supplier, user = inventory_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _receive_stock(tenant, supplier, location, variant_id, Decimal("100"))
        _accounting_config(tenant)

        inventory = create_inventory(
            tenant=tenant, warehouse=warehouse, date=dt.date(2026, 1, 15), type="ponctuel"
        )
        line = add_inventory_line(inventory, variant_id=variant_id, location=location)
        start_inventory(inventory)
        record_count(line, qty_counted=Decimal("90"), counted_by=user, reason="Casse constatee")
        line.refresh_from_db()
        assert line.difference == Decimal("-10.0000")

        validate_inventory(inventory, validated_by=user)

        quant = get_quant(variant_id, location)
        assert quant is not None
        assert quant.qty == Decimal("90.0000")

        adjustment_move = StkMove.objects.get(
            variant_id=variant_id, move_type=StkMove.TYPE_AJUSTEMENT
        )
        assert adjustment_move.location_from_id == location.id
        assert adjustment_move.qty == Decimal("10.0000")


def test_record_count_within_threshold_no_reason_required(inventory_setup) -> None:
    tenant, warehouse, location, supplier, user = inventory_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _receive_stock(tenant, supplier, location, variant_id, Decimal("100"))
        inventory = create_inventory(
            tenant=tenant, warehouse=warehouse, date=dt.date(2026, 1, 15), type="ponctuel"
        )
        line = add_inventory_line(inventory, variant_id=variant_id, location=location)
        start_inventory(inventory)
        # 2% d'ecart, sous le seuil par defaut (5%) : aucun motif requis.
        record_count(line, qty_counted=Decimal("98"), counted_by=user)
        line.refresh_from_db()
        assert line.difference == Decimal("-2.0000")
        assert line.reason == ""


def test_record_count_above_threshold_without_reason_refused(inventory_setup) -> None:
    tenant, warehouse, location, supplier, user = inventory_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _receive_stock(tenant, supplier, location, variant_id, Decimal("100"))
        inventory = create_inventory(
            tenant=tenant, warehouse=warehouse, date=dt.date(2026, 1, 15), type="ponctuel"
        )
        line = add_inventory_line(inventory, variant_id=variant_id, location=location)
        start_inventory(inventory)
        # 20% d'ecart, au-dessus du seuil par defaut (5%) : motif requis.
        with pytest.raises(ValidationError):
            record_count(line, qty_counted=Decimal("80"), counted_by=user)


def test_record_count_above_threshold_with_reason_succeeds(inventory_setup) -> None:
    tenant, warehouse, location, supplier, user = inventory_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _receive_stock(tenant, supplier, location, variant_id, Decimal("100"))
        inventory = create_inventory(
            tenant=tenant, warehouse=warehouse, date=dt.date(2026, 1, 15), type="ponctuel"
        )
        line = add_inventory_line(inventory, variant_id=variant_id, location=location)
        start_inventory(inventory)
        record_count(line, qty_counted=Decimal("80"), counted_by=user, reason="Casse non tracee")
        line.refresh_from_db()
        assert line.reason == "Casse non tracee"
        assert line.difference == Decimal("-20.0000")


def test_record_count_guards_zero_theoretical(inventory_setup) -> None:
    """Ligne sans quant existant (theorique nul) : compter quoi que ce
    soit dessus est TOUJOURS un ecart maximal (100%), meme traitement
    "bloquant" que `purchase.services.invoicing.three_way_match`."""
    tenant, warehouse, location, _supplier, user = inventory_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        inventory = create_inventory(
            tenant=tenant, warehouse=warehouse, date=dt.date(2026, 1, 15), type="ponctuel"
        )
        line = add_inventory_line(inventory, variant_id=variant_id, location=location)
        assert line.qty_theoretical == Decimal("0")
        start_inventory(inventory)
        with pytest.raises(ValidationError):
            record_count(line, qty_counted=Decimal("10"), counted_by=user)
        # Rien compte sur rien attendu : 0%, aucun motif requis.
        record_count(line, qty_counted=Decimal("0"), counted_by=user)


def test_validate_inventory_refuses_uncounted_lines(inventory_setup) -> None:
    tenant, warehouse, location, supplier, user = inventory_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _receive_stock(tenant, supplier, location, variant_id, Decimal("100"))
        inventory = create_inventory(
            tenant=tenant, warehouse=warehouse, date=dt.date(2026, 1, 15), type="ponctuel"
        )
        add_inventory_line(inventory, variant_id=variant_id, location=location)
        start_inventory(inventory)
        with pytest.raises(ValidationError):
            validate_inventory(inventory, validated_by=user)


def test_validate_inventory_proceeds_even_without_accounting_config(inventory_setup) -> None:
    """L'ecriture comptable de regularisation retombe silencieusement a
    `None` (gap de configuration, meme discipline que les autres gaps
    `accounting.services.public`) sans jamais bloquer la validation de
    l'inventaire lui-meme."""
    tenant, warehouse, location, supplier, user = inventory_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _receive_stock(tenant, supplier, location, variant_id, Decimal("100"))
        inventory = create_inventory(
            tenant=tenant, warehouse=warehouse, date=dt.date(2026, 1, 15), type="ponctuel"
        )
        line = add_inventory_line(inventory, variant_id=variant_id, location=location)
        start_inventory(inventory)
        record_count(line, qty_counted=Decimal("105"), counted_by=user)

        validate_inventory(inventory, validated_by=user)
        inventory.refresh_from_db()
        assert inventory.state == StkInventory.STATE_VALIDATED


def test_cancel_inventory_requires_reason(inventory_setup) -> None:
    tenant, warehouse, _location, _supplier, _user = inventory_setup
    with use_tenant(tenant.id):
        inventory = create_inventory(
            tenant=tenant, warehouse=warehouse, date=dt.date(2026, 1, 15), type="ponctuel"
        )
        with pytest.raises(ValidationError):
            cancel_inventory(inventory, reason="")
        cancel_inventory(inventory, reason="Erreur de saisie")
        inventory.refresh_from_db()
        assert inventory.state == StkInventory.STATE_CANCELLED


def test_cancel_inventory_refuses_validated(inventory_setup) -> None:
    tenant, warehouse, location, supplier, user = inventory_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _receive_stock(tenant, supplier, location, variant_id, Decimal("100"))
        inventory = create_inventory(
            tenant=tenant, warehouse=warehouse, date=dt.date(2026, 1, 15), type="ponctuel"
        )
        line = add_inventory_line(inventory, variant_id=variant_id, location=location)
        start_inventory(inventory)
        record_count(line, qty_counted=Decimal("100"), counted_by=user)
        validate_inventory(inventory, validated_by=user)
        with pytest.raises(ValidationError):
            cancel_inventory(inventory, reason="trop tard")


def test_start_inventory_refuses_with_zero_lines(inventory_setup) -> None:
    tenant, warehouse, _location, _supplier, _user = inventory_setup
    with use_tenant(tenant.id):
        inventory = create_inventory(
            tenant=tenant, warehouse=warehouse, date=dt.date(2026, 1, 15), type="ponctuel"
        )
        with pytest.raises(ValidationError):
            start_inventory(inventory)


def test_add_inventory_line_refuses_after_draft(inventory_setup) -> None:
    tenant, warehouse, location, supplier, user = inventory_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _receive_stock(tenant, supplier, location, variant_id, Decimal("100"))
        inventory = create_inventory(
            tenant=tenant, warehouse=warehouse, date=dt.date(2026, 1, 15), type="ponctuel"
        )
        add_inventory_line(inventory, variant_id=variant_id, location=location)
        start_inventory(inventory)
        with pytest.raises(ValidationError):
            add_inventory_line(inventory, variant_id=variant_id, location=location)


def test_default_variance_threshold_pct_is_five() -> None:
    assert Decimal("5") == DEFAULT_VARIANCE_THRESHOLD_PCT
