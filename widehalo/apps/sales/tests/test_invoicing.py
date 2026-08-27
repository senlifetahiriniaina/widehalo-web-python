"""Tests RG-SAL-2 (politique de facturation par ligne) / SAL-AVCT1
(facturation a l'avancement de production) — S4 du sous-sequencement
`sales` (cf. plan). Couvre `services.invoicing.invoiceable_amount_for_line`
et `services.invoicing.invoice_order`."""

from __future__ import annotations

import calendar
import datetime as dt
from decimal import Decimal

import pytest

from apps.accounting.models import AccAccount, AccJournal
from apps.accounting.tests.factories import AccAccountFactory, AccJournalFactory, AccPeriodFactory
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.mrp.tests.factories import MrpOrderFactory
from apps.partners.tests.factories import PartnerFactory
from apps.sales.models import SalesOrder, SalesOrderLine
from apps.sales.services.invoicing import invoice_order, invoiceable_amount_for_line
from apps.sales.services.orders import (
    add_order_line,
    confirm_order,
    create_order,
    mark_delivered,
    start_preparation,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def invoicing_setup():
    tenant = Tenant.objects.create(code="SALES-INV", name="Sales Invoicing Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="sales-inv@example.com", password="Str0ngPassw0rd!23")
        partner = PartnerFactory(tenant=tenant)
        return tenant, user, partner


def _setup_accounting(tenant: Tenant) -> None:
    """Cree la configuration comptable minimale attendue par
    `accounting.services.public.create_customer_invoice_from_source`."""
    AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_SALE)
    today = dt.date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    AccPeriodFactory(
        tenant=tenant, date_start=today.replace(day=1), date_end=today.replace(day=last_day)
    )
    AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_RECEIVABLE)
    AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_INCOME)


# --- invoiceable_amount_for_line -------------------------------------------------


def test_invoiceable_amount_on_ordered_qty_is_full_subtotal_once(invoicing_setup) -> None:
    tenant, _user, partner = invoicing_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        line = add_order_line(
            order,
            description="Ligne",
            qty=Decimal("2"),
            unit_price=Decimal("1000"),
            is_custom=True,
            billing_policy=SalesOrderLine.BILLING_ON_ORDERED_QTY,
        )
        assert invoiceable_amount_for_line(line) == Decimal("2000.0000")

        # Idempotent : une fois `qty_invoiced` a jour, plus rien a facturer.
        line.qty_invoiced = line.qty
        line.save(update_fields=["qty_invoiced"])
        assert invoiceable_amount_for_line(line) == Decimal(0)


def test_invoiceable_amount_on_delivered_qty_is_proportional(invoicing_setup) -> None:
    tenant, _user, partner = invoicing_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        line = add_order_line(
            order,
            description="Ligne",
            qty=Decimal("10"),
            unit_price=Decimal("100"),
            is_custom=True,
            billing_policy=SalesOrderLine.BILLING_ON_DELIVERED_QTY,
        )
        line.qty_delivered = Decimal("4")
        line.save(update_fields=["qty_delivered"])

        assert invoiceable_amount_for_line(line) == Decimal("400.0000")


def test_invoiceable_amount_on_deposit_two_phases(invoicing_setup) -> None:
    tenant, _user, partner = invoicing_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        line = add_order_line(
            order,
            description="Ligne",
            qty=Decimal("10"),
            unit_price=Decimal("100"),
            is_custom=True,
            billing_policy=SalesOrderLine.BILLING_ON_DEPOSIT,
            deposit_pct=Decimal("30"),
        )
        # Phase 1 : acompte de 30% de 1000 = 300.
        assert invoiceable_amount_for_line(line) == Decimal("300.0000")

        # L'acompte est facture (qty_invoiced reflete les 300 deja
        # factures) mais la ligne n'est pas encore livree : rien de plus.
        line.qty_invoiced = Decimal("3")
        line.save(update_fields=["qty_invoiced"])
        assert invoiceable_amount_for_line(line) == Decimal(0)

        # Une fois livree, le solde (1000 - 300 = 700) devient facturable
        # (la "facture finale" a laquelle l'acompte est repute impute).
        line.qty_delivered = line.qty
        line.save(update_fields=["qty_delivered"])
        assert invoiceable_amount_for_line(line) == Decimal("700.0000")


def test_invoiceable_amount_on_production_progress(invoicing_setup) -> None:
    tenant, _user, partner = invoicing_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        mrp_order = MrpOrderFactory(tenant=tenant, qty=Decimal("20"), qty_produced=Decimal("5"))
        line = add_order_line(
            order,
            description="Ligne production",
            qty=Decimal("20"),
            unit_price=Decimal("50"),
            is_custom=True,
            source=SalesOrderLine.SOURCE_PRODUCTION,
            billing_policy=SalesOrderLine.BILLING_ON_PRODUCTION_PROGRESS,
            mrp_order_id=mrp_order.id,
        )
        # 5/20 produit -> 25% de 1000 = 250.
        assert invoiceable_amount_for_line(line) == Decimal("250.0000")


def test_invoiceable_amount_on_production_progress_without_mrp_order_is_zero(
    invoicing_setup,
) -> None:
    tenant, _user, partner = invoicing_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        line = add_order_line(
            order,
            description="Ligne production sans OF",
            qty=Decimal("5"),
            unit_price=Decimal("100"),
            is_custom=True,
            source=SalesOrderLine.SOURCE_PRODUCTION,
            billing_policy=SalesOrderLine.BILLING_ON_PRODUCTION_PROGRESS,
        )
        assert invoiceable_amount_for_line(line) == Decimal(0)


# --- invoice_order -----------------------------------------------------------------


def _confirmed_delivered_order(tenant, user, partner, **line_kwargs) -> SalesOrder:
    order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
    add_order_line(
        order,
        description="Ligne",
        qty=Decimal("2"),
        unit_price=Decimal("1000"),
        is_custom=True,
        **line_kwargs,
    )
    confirm_order(order, user)
    start_preparation(order, user)
    mark_delivered(order, user)
    order.refresh_from_db()
    return order


def test_invoice_order_returns_none_without_accounting_config(invoicing_setup) -> None:
    tenant, user, partner = invoicing_setup
    with use_tenant(tenant.id):
        order = _confirmed_delivered_order(tenant, user, partner)
        original_state = order.state

        result = invoice_order(order, user)

        assert result is None
        order.refresh_from_db()
        assert order.state == original_state
        assert order.invoiced_amount_mga == Decimal(0)
        assert order.lines.first().qty_invoiced == Decimal(0)


def test_invoice_order_transitions_order_to_invoiced_once_fully_billed(invoicing_setup) -> None:
    tenant, user, partner = invoicing_setup
    with use_tenant(tenant.id):
        _setup_accounting(tenant)
        order = _confirmed_delivered_order(tenant, user, partner)

        invoice_id = invoice_order(order, user)

        assert invoice_id is not None
        order.refresh_from_db()
        assert order.state == SalesOrder.STATE_INVOICED
        assert order.invoiced_amount_mga == Decimal("2000.0000")
        line = order.lines.first()
        assert line.qty_invoiced == line.qty


def test_invoice_order_partial_invoicing_leaves_order_delivered(invoicing_setup) -> None:
    tenant, user, partner = invoicing_setup
    with use_tenant(tenant.id):
        _setup_accounting(tenant)
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        add_order_line(
            order,
            description="Ligne 1",
            qty=Decimal("2"),
            unit_price=Decimal("1000"),
            is_custom=True,
        )
        add_order_line(
            order,
            description="Ligne 2",
            qty=Decimal("1"),
            unit_price=Decimal("500"),
            is_custom=True,
        )
        confirm_order(order, user)
        start_preparation(order, user)
        mark_delivered(order, user)
        order.refresh_from_db()

        first_line = order.lines.order_by("sequence").first()
        invoice_id = invoice_order(order, user, lines=[first_line])

        assert invoice_id is not None
        order.refresh_from_db()
        # 2000 factures sur 2500 dus : pas encore entierement facturee.
        assert order.state == SalesOrder.STATE_DELIVERED
        assert order.invoiced_amount_mga == Decimal("2000.0000")


def test_invoice_order_with_nothing_invoiceable_returns_none(invoicing_setup) -> None:
    tenant, user, partner = invoicing_setup
    with use_tenant(tenant.id):
        _setup_accounting(tenant)
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        add_order_line(
            order,
            description="Ligne livree seulement",
            qty=Decimal("5"),
            unit_price=Decimal("100"),
            is_custom=True,
            billing_policy=SalesOrderLine.BILLING_ON_DELIVERED_QTY,
        )
        # Pas encore livree : `on_delivered_qty` ne facture rien.
        result = invoice_order(order, user)
        assert result is None
        order.refresh_from_db()
        assert order.invoiced_amount_mga == Decimal(0)
