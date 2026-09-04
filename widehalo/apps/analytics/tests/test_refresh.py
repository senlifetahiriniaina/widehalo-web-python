"""Rafraîchissement de l'entrepôt (`services/refresh.py`) : upsert
idempotent, jalons incrémentaux, verrou anti-concurrence, contrôle de
réconciliation (cahier Phase 2 §12)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccPayment, AccPeriod
from apps.accounting.services.moves import add_line, create_draft_move, post_move
from apps.analytics.models import (
    AnDimArticle,
    AnDimTiers,
    AnFactEcriture,
    AnFactEncaissement,
    AnFactMouvementStock,
    AnFactTicketPos,
    AnFactVente,
    AnRefreshRun,
    AnWarehouseState,
)
from apps.analytics.services.refresh import refresh_warehouse_for_tenant
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.partners.tests.factories import PartnerFactory
from apps.pos.models import PosOrder
from apps.pos.tests.factories import PosOrderFactory, PosOrderLineFactory
from apps.sales.models import SalesOrder, SalesOrderLine
from apps.stocks.models import StkMove
from apps.stocks.tests.factories import StkMoveFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def warehouse_tenant() -> Tenant:
    return Tenant.objects.create(code="AN-WH", name="Analytics Warehouse Tenant")


def _make_order_line(tenant: Tenant, *, partner_id, subtotal: Decimal) -> SalesOrderLine:
    order = SalesOrder.objects.create(
        tenant=tenant,
        partner_id=partner_id,
        date=dt.date(2026, 9, 1),
        amount_untaxed=subtotal,
        amount_total=subtotal,
        amount_total_mga=subtotal,
    )
    return SalesOrderLine.objects.create(
        tenant=tenant,
        order=order,
        description="Article test",
        qty=Decimal("1"),
        unit_price=subtotal,
        subtotal=subtotal,
    )


def test_refresh_populates_dims_and_facts(warehouse_tenant: Tenant) -> None:
    with use_tenant(warehouse_tenant.id):
        partner = PartnerFactory(tenant=warehouse_tenant, name="Client Test")
        _make_order_line(warehouse_tenant, partner_id=partner.id, subtotal=Decimal("10000"))

    run = refresh_warehouse_for_tenant(warehouse_tenant, triggered_by=AnRefreshRun.TRIGGER_MANUAL)

    assert run.status == AnRefreshRun.STATUS_SUCCESS
    assert run.rows_processed == 1
    assert run.reconciliation_ok is True

    with use_tenant(warehouse_tenant.id):
        assert AnDimTiers.objects.filter(tenant=warehouse_tenant).count() == 1
        fact = AnFactVente.objects.get(tenant=warehouse_tenant)
        assert fact.montant_ht_mga == Decimal("10000")
        assert fact.dim_tiers.nom == "Client Test"
        assert fact.dim_temps.date == dt.date(2026, 9, 1)
        assert fact.dim_temps.annee == 2026
        assert fact.dim_temps.mois == 9


def test_refresh_is_incremental_and_idempotent(warehouse_tenant: Tenant) -> None:
    with use_tenant(warehouse_tenant.id):
        partner = PartnerFactory(tenant=warehouse_tenant)
        _make_order_line(warehouse_tenant, partner_id=partner.id, subtotal=Decimal("10000"))

    first_run = refresh_warehouse_for_tenant(warehouse_tenant)
    assert first_run.rows_processed == 1

    # Rejouer immediatement sans nouvelle donnee : rien de neuf a traiter,
    # mais le meme upsert reste idempotent (pas de doublon en base).
    second_run = refresh_warehouse_for_tenant(warehouse_tenant)
    assert second_run.rows_processed == 0
    with use_tenant(warehouse_tenant.id):
        assert AnFactVente.objects.filter(tenant=warehouse_tenant).count() == 1

    with use_tenant(warehouse_tenant.id):
        partner2 = PartnerFactory(tenant=warehouse_tenant)
        _make_order_line(warehouse_tenant, partner_id=partner2.id, subtotal=Decimal("5000"))

    third_run = refresh_warehouse_for_tenant(warehouse_tenant)
    assert third_run.rows_processed == 1
    with use_tenant(warehouse_tenant.id):
        assert AnFactVente.objects.filter(tenant=warehouse_tenant).count() == 2
        assert AnDimTiers.objects.filter(tenant=warehouse_tenant).count() == 2


def test_refresh_respects_active_lock(warehouse_tenant: Tenant) -> None:
    with use_tenant(warehouse_tenant.id):
        AnWarehouseState.objects.create(tenant=warehouse_tenant, is_locked=True)

    run = refresh_warehouse_for_tenant(warehouse_tenant)

    assert run.status == AnRefreshRun.STATUS_FAILED
    assert "verrou" in run.error_message.lower()
    with use_tenant(warehouse_tenant.id):
        assert AnFactVente.objects.filter(tenant=warehouse_tenant).count() == 0


def test_refresh_excludes_cancelled_orders(warehouse_tenant: Tenant) -> None:
    with use_tenant(warehouse_tenant.id):
        partner = PartnerFactory(tenant=warehouse_tenant)
        line = _make_order_line(warehouse_tenant, partner_id=partner.id, subtotal=Decimal("10000"))
        line.order.state = SalesOrder.STATE_CANCELLED
        line.order.save(update_fields=["state"])

    run = refresh_warehouse_for_tenant(warehouse_tenant)

    assert run.rows_processed == 0
    with use_tenant(warehouse_tenant.id):
        assert AnFactVente.objects.filter(tenant=warehouse_tenant).count() == 0


def test_refresh_leaves_no_dim_article_when_variant_id_absent(warehouse_tenant: Tenant) -> None:
    """`SalesOrderLine.variant_id` est nullable (ligne "custom") : la ligne
    doit quand meme etre remontee en fait, avec `dim_article=None`, jamais
    une exception."""
    with use_tenant(warehouse_tenant.id):
        partner = PartnerFactory(tenant=warehouse_tenant)
        _make_order_line(warehouse_tenant, partner_id=partner.id, subtotal=Decimal("1000"))

    run = refresh_warehouse_for_tenant(warehouse_tenant)

    assert run.status == AnRefreshRun.STATUS_SUCCESS
    with use_tenant(warehouse_tenant.id):
        fact = AnFactVente.objects.get(tenant=warehouse_tenant)
        assert fact.dim_article is None
        assert AnDimArticle.objects.filter(tenant=warehouse_tenant).count() == 0


def test_refresh_populates_pos_and_accounting_facts(warehouse_tenant: Tenant) -> None:
    with use_tenant(warehouse_tenant.id):
        order = PosOrderFactory(
            tenant=warehouse_tenant,
            state=PosOrder.STATE_VALIDATED,
            number="CAISSE-1-000001",
        )
        PosOrderLineFactory(
            tenant=warehouse_tenant,
            order=order,
            subtotal=Decimal("8000"),
            tax_amount=Decimal("1440"),
            total=Decimal("9440"),
        )

        journal = AccJournal.objects.create(
            tenant=warehouse_tenant,
            code="OD",
            name="Opérations diverses",
            type=AccJournal.TYPE_MISC,
            sequence_prefix="OD",
        )
        fiscal_year = AccFiscalYear.objects.create(
            tenant=warehouse_tenant,
            code="FY2026",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 12, 31),
        )
        period = AccPeriod.objects.create(
            tenant=warehouse_tenant,
            fiscal_year=fiscal_year,
            code="2026-09",
            date_start=dt.date(2026, 9, 1),
            date_end=dt.date(2026, 9, 30),
        )
        income = AccAccount.objects.create(
            tenant=warehouse_tenant,
            code="701",
            name="Ventes",
            account_class=7,
            type=AccAccount.TYPE_INCOME,
        )
        bank = AccAccount.objects.create(
            tenant=warehouse_tenant,
            code="512",
            name="Banque",
            account_class=5,
            type=AccAccount.TYPE_BANK,
        )
        move = create_draft_move(
            tenant=warehouse_tenant, journal=journal, period=period, date=dt.date(2026, 9, 2)
        )
        add_line(move, account=bank, label="Encaissement", debit=Decimal("20000"))
        add_line(move, account=income, label="Vente", credit=Decimal("20000"))
        post_move(move)

        AccPayment.objects.create(
            tenant=warehouse_tenant,
            journal=journal,
            date=dt.date(2026, 9, 3),
            amount=Decimal("20000"),
            direction=AccPayment.DIRECTION_INBOUND,
            method=AccPayment.METHOD_CASH,
            state=AccPayment.STATE_POSTED,
        )

    run = refresh_warehouse_for_tenant(warehouse_tenant)

    assert run.status == AnRefreshRun.STATUS_SUCCESS
    with use_tenant(warehouse_tenant.id):
        ticket = AnFactTicketPos.objects.get(tenant=warehouse_tenant)
        assert ticket.montant_ttc_mga == Decimal("9440")
        assert ticket.point_vente_code == order.register.code

        ecritures = list(
            AnFactEcriture.objects.filter(tenant=warehouse_tenant).order_by("compte_code")
        )
        assert [e.compte_code for e in ecritures] == ["512", "701"]
        assert ecritures[0].debit_mga == Decimal("20000")
        assert ecritures[1].credit_mga == Decimal("20000")

        encaissement = AnFactEncaissement.objects.get(tenant=warehouse_tenant)
        assert encaissement.montant_mga == Decimal("20000")
        assert encaissement.direction == AccPayment.DIRECTION_INBOUND


def test_refresh_populates_stock_move_fact(warehouse_tenant: Tenant) -> None:
    """Bloc Transverse, T1 (FOR-11) — `StkMove` validé (`state=done`)
    matérialisé en `AnFactMouvementStock`, un mouvement `draft` ignoré."""
    with use_tenant(warehouse_tenant.id):
        StkMoveFactory(tenant=warehouse_tenant, state=StkMove.STATE_DRAFT)
        move = StkMoveFactory(
            tenant=warehouse_tenant,
            state=StkMove.STATE_DONE,
            date=dt.date(2026, 9, 4),
            qty=Decimal("15"),
            unit_cost_mga=Decimal("200"),
            value_mga=Decimal("3000"),
            source_document="OF-T1-REFRESH",
        )

    run = refresh_warehouse_for_tenant(warehouse_tenant)

    assert run.status == AnRefreshRun.STATUS_SUCCESS
    assert run.rows_processed == 1
    with use_tenant(warehouse_tenant.id):
        fact = AnFactMouvementStock.objects.get(tenant=warehouse_tenant)
        assert fact.source_move_id == move.id
        assert fact.qty == Decimal("15")
        assert fact.value_mga == Decimal("3000")
        assert fact.move_type == move.move_type
        assert fact.entrepot_origine_code == move.location_from.warehouse.code
        assert fact.entrepot_destination_code == move.location_to.warehouse.code
        assert fact.dim_temps.date == dt.date(2026, 9, 4)
