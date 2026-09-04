"""Tests RG-PUR-6 (controle facture 3 voies) : `apps/purchase/services/
invoicing.py`."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounting.models import AccAccount, AccJournal, AccMove, AccPeriod
from apps.accounting.tests.factories import (
    AccAccountFactory,
    AccJournalFactory,
    AccPeriodFactory,
)
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.purchase.models import PurOrder, PurReceiptLine
from apps.purchase.services.invoicing import (
    DEFAULT_VARIANCE_THRESHOLD_PCT,
    record_supplier_invoice,
    three_way_match,
)
from apps.purchase.services.orders import (
    add_order_line,
    confirm_order,
    create_order,
    mark_order_in_transit,
    send_order,
    submit_order_for_validation,
    validate_order,
)
from apps.purchase.services.receiving import receive_order_line
from apps.stocks.models import StkLocation, StkWarehouse

pytestmark = pytest.mark.django_db


@pytest.fixture
def invoicing_setup():
    tenant = Tenant.objects.create(code="PUR-INV", name="Purchase Invoicing Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="pur-inv@example.com", password="Str0ngPassw0rd!23")
        return tenant, user


def _accounting_config(tenant: Tenant) -> tuple[AccJournal, AccPeriod, AccAccount, AccAccount]:
    """Cree le parametrage comptable minimal (journal achat, periode
    ouverte, compte fournisseur, compte de charge) requis par
    `accounting.services.public.create_supplier_invoice_from_source`."""
    journal = AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_PURCHASE)
    period = AccPeriodFactory(
        tenant=tenant,
        date_start=dt.date(2026, 1, 1),
        date_end=dt.date(2026, 12, 31),
    )
    payable = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_PAYABLE)
    expense = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_EXPENSE)
    return journal, period, payable, expense


def _received_order(tenant, user) -> PurOrder:
    """B4 (Phase 3, ACH-8) : réceptionne RÉELLEMENT la commande via
    `receive_order_line` (entrepôt + emplacement interne configurés, même
    patron que `apps.purchase.tests.test_receiving.receiving_setup`) —
    plutôt que de sauter directement à `mark_order_received` (raccourci
    qui, avant ce sprint, laissait `PurOrderLine.qty_received` à 0 pour
    TOUTE la suite de tests ci-dessous, rendant invisible le nouveau
    contrôle de quantité réellement reçue de `three_way_match`).
    `receive_order_line` transitionne déjà automatiquement la commande
    vers `received` (réception complète) — `mark_order_received` explicite
    n'est plus nécessaire."""
    warehouse = StkWarehouse.objects.create(tenant=tenant, code="WH-INV", name="Entrepôt")
    StkLocation.objects.create(
        tenant=tenant,
        warehouse=warehouse,
        code="WH-INV-A1",
        name="Rayon A1",
        type=StkLocation.TYPE_INTERNE,
    )
    order = create_order(
        tenant=tenant,
        partner_id=uuid.uuid4(),
        date=timezone.now().date(),
        warehouse_id=warehouse.id,
    )
    line = add_order_line(
        order,
        variant_id=uuid.uuid4(),
        description="Fil",
        qty=Decimal(10),
        unit_price_mga=Decimal(1000),
    )
    submit_order_for_validation(order, user)
    validate_order(order, user)
    send_order(order, user)
    confirm_order(order, user)
    mark_order_in_transit(order, user)
    receive_order_line(
        line,
        qty_received_now=Decimal(10),
        quality_status=PurReceiptLine.QUALITY_CONFORME,
        user=user,
    )
    order.refresh_from_db()
    return order


def test_three_way_match_within_threshold_is_not_blocked(invoicing_setup) -> None:
    tenant, user = invoicing_setup
    with use_tenant(tenant.id):
        order = _received_order(tenant, user)
        order_line = order.lines.first()

        match = three_way_match(
            order,
            invoice_lines=[
                {
                    "order_line_id": order_line.id,
                    "qty_invoiced": Decimal(10),
                    "unit_price_mga": Decimal(1010),
                }
            ],
        )

        assert match["blocked"] is False
        assert match["lines"][0]["variance_pct"] == Decimal(1)
        assert match["max_variance_pct"] == Decimal(1)


def test_three_way_match_over_threshold_is_blocked(invoicing_setup) -> None:
    """Acceptance test §5.6.7 n°4 : "Une facture superieure de 5% au bon de
    commande bloque la validation et ouvre un litige" — ecart de facture
    de +5% (bien au-dela du seuil par defaut de 2%)."""
    tenant, user = invoicing_setup
    with use_tenant(tenant.id):
        order = _received_order(tenant, user)
        order_line = order.lines.first()

        match = three_way_match(
            order,
            invoice_lines=[
                {
                    "order_line_id": order_line.id,
                    "qty_invoiced": Decimal(10),
                    "unit_price_mga": Decimal(1050),
                }
            ],
        )

        assert match["blocked"] is True
        assert match["lines"][0]["variance_pct"] == Decimal(5)
        assert match["max_variance_pct"] == Decimal(5)


def test_three_way_match_zero_ordered_amount_is_a_blocking_edge_case(invoicing_setup) -> None:
    tenant, user = invoicing_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=timezone.now().date())
        order_line = add_order_line(
            order,
            variant_id=uuid.uuid4(),
            description="Gratuit",
            qty=Decimal(10),
            unit_price_mga=Decimal(0),
        )

        # Rien facture sur une ligne commandee a 0 : ecart nul, pas un
        # ZeroDivisionError.
        match_zero = three_way_match(
            order,
            invoice_lines=[
                {
                    "order_line_id": order_line.id,
                    "qty_invoiced": Decimal(0),
                    "unit_price_mga": Decimal(0),
                }
            ],
        )
        assert match_zero["blocked"] is False
        assert match_zero["lines"][0]["variance_pct"] == Decimal(0)

        # Un montant non nul facture sur une ligne commandee a 0 : ecart
        # maximal (100%), toujours bloquant.
        match_nonzero = three_way_match(
            order,
            invoice_lines=[
                {
                    "order_line_id": order_line.id,
                    "qty_invoiced": Decimal(10),
                    "unit_price_mga": Decimal(5),
                }
            ],
        )
        assert match_nonzero["blocked"] is True
        assert match_nonzero["lines"][0]["variance_pct"] == Decimal(100)


def test_three_way_match_flags_qty_variance_when_invoicing_beyond_actual_receipt(
    invoicing_setup,
) -> None:
    """B4 (Phase 3, ACH-8 : "rapprochement à trois voies RÉEL") : avant ce
    sprint, `three_way_match` ne comparait QUE le montant commandé au
    montant facturé — une facture dont le MONTANT correspond exactement à
    la commande passait sans encombre même si la marchandise n'avait été
    que PARTIELLEMENT réceptionnée (erreur/fraude classique que le
    contrôle à 3 voies est précisément censé empêcher)."""
    tenant, user = invoicing_setup
    with use_tenant(tenant.id):
        warehouse = StkWarehouse.objects.create(tenant=tenant, code="WH-INV-2", name="Entrepôt")
        StkLocation.objects.create(
            tenant=tenant,
            warehouse=warehouse,
            code="WH-INV-2-A1",
            name="Rayon A1",
            type=StkLocation.TYPE_INTERNE,
        )
        order = create_order(
            tenant=tenant,
            partner_id=uuid.uuid4(),
            date=timezone.now().date(),
            warehouse_id=warehouse.id,
        )
        line = add_order_line(
            order,
            variant_id=uuid.uuid4(),
            description="Fil",
            qty=Decimal(10),
            unit_price_mga=Decimal(1000),
        )
        submit_order_for_validation(order, user)
        validate_order(order, user)
        send_order(order, user)
        confirm_order(order, user)
        mark_order_in_transit(order, user)
        # Réception PARTIELLE seulement (6 sur 10).
        receive_order_line(
            line,
            qty_received_now=Decimal(6),
            quality_status=PurReceiptLine.QUALITY_CONFORME,
            user=user,
        )

        # La facture correspond EXACTEMENT à la commande (0% d'écart de
        # montant) mais facture les 10 unités alors que seules 6 ont été
        # reçues.
        match = three_way_match(
            order,
            invoice_lines=[
                {
                    "order_line_id": line.id,
                    "qty_invoiced": Decimal(10),
                    "unit_price_mga": Decimal(1000),
                }
            ],
        )

        row = match["lines"][0]
        assert row["amount_variance_pct"] == Decimal(0)
        assert row["qty_available_to_invoice"] == Decimal(6)
        assert row["qty_variance_pct"] > Decimal(0)
        assert match["blocked"] is True


def test_three_way_match_qty_leg_is_not_triggered_within_actual_receipt(invoicing_setup) -> None:
    """Facturer seulement ce qui a été réellement reçu ne doit jamais
    déclencher la jambe QUANTITÉ, même si la jambe MONTANT (comparée à la
    commande COMPLÈTE — comportement préexistant, hors périmètre de ce
    sprint) reste élevée pour une facture partielle."""
    tenant, user = invoicing_setup
    with use_tenant(tenant.id):
        warehouse = StkWarehouse.objects.create(tenant=tenant, code="WH-INV-3", name="Entrepôt")
        StkLocation.objects.create(
            tenant=tenant,
            warehouse=warehouse,
            code="WH-INV-3-A1",
            name="Rayon A1",
            type=StkLocation.TYPE_INTERNE,
        )
        order = create_order(
            tenant=tenant,
            partner_id=uuid.uuid4(),
            date=timezone.now().date(),
            warehouse_id=warehouse.id,
        )
        line = add_order_line(
            order,
            variant_id=uuid.uuid4(),
            description="Fil",
            qty=Decimal(10),
            unit_price_mga=Decimal(1000),
        )
        submit_order_for_validation(order, user)
        validate_order(order, user)
        send_order(order, user)
        confirm_order(order, user)
        mark_order_in_transit(order, user)
        receive_order_line(
            line,
            qty_received_now=Decimal(6),
            quality_status=PurReceiptLine.QUALITY_CONFORME,
            user=user,
        )

        match = three_way_match(
            order,
            invoice_lines=[
                {
                    "order_line_id": line.id,
                    "qty_invoiced": Decimal(6),
                    "unit_price_mga": Decimal(1000),
                }
            ],
        )
        assert match["lines"][0]["qty_variance_pct"] == Decimal(0)


def test_record_supplier_invoice_happy_path_creates_invoice_and_transitions(
    invoicing_setup,
) -> None:
    tenant, user = invoicing_setup
    with use_tenant(tenant.id):
        _accounting_config(tenant)
        order = _received_order(tenant, user)
        order_line = order.lines.first()

        result = record_supplier_invoice(
            order,
            invoice_lines=[
                {
                    "order_line_id": order_line.id,
                    "qty_invoiced": Decimal(10),
                    "unit_price_mga": Decimal(1000),
                }
            ],
            date=dt.date(2026, 1, 20),
            user=user,
        )

        assert result["dispute_opened"] is False
        assert result["invoice_id"] is not None
        move = AccMove.objects.get(id=result["invoice_id"])
        assert move.move_type == AccMove.TYPE_SUPPLIER_INVOICE

        order_line.refresh_from_db()
        assert order_line.qty_invoiced == Decimal(10)

        order.refresh_from_db()
        assert order.state == PurOrder.STATE_INVOICED


def test_record_supplier_invoice_populates_received_by_ids_from_receipt_lines(
    invoicing_setup,
) -> None:
    """B5 (Phase 3, ACH-9) : `record_supplier_invoice` doit transmettre les
    UUID de TOUS les utilisateurs ayant réceptionné une ligne de la
    commande à `accounting`, pour que `validate_invoice` puisse ensuite
    appliquer la séparation des tâches."""
    tenant, user = invoicing_setup
    with use_tenant(tenant.id):
        _accounting_config(tenant)
        order = _received_order(tenant, user)
        order_line = order.lines.first()

        result = record_supplier_invoice(
            order,
            invoice_lines=[
                {
                    "order_line_id": order_line.id,
                    "qty_invoiced": Decimal(10),
                    "unit_price_mga": Decimal(1000),
                }
            ],
            date=dt.date(2026, 1, 20),
            user=user,
        )

        move = AccMove.objects.get(id=result["invoice_id"])
        assert move.received_by_ids == [str(user.id)]


def test_record_supplier_invoice_blocked_opens_dispute_and_creates_no_invoice(
    invoicing_setup,
) -> None:
    """Acceptance test §5.6.7 n°4 : la facture depassant le seuil de +5%
    ne cree AUCUNE `AccMove` et ouvre un litige a la place."""
    tenant, user = invoicing_setup
    with use_tenant(tenant.id):
        _accounting_config(tenant)
        order = _received_order(tenant, user)
        order_line = order.lines.first()

        result = record_supplier_invoice(
            order,
            invoice_lines=[
                {
                    "order_line_id": order_line.id,
                    "qty_invoiced": Decimal(10),
                    "unit_price_mga": Decimal(1050),
                }
            ],
            date=dt.date(2026, 1, 20),
            user=user,
        )

        assert result["dispute_opened"] is True
        assert result["invoice_id"] is None
        assert result["match"]["blocked"] is True
        assert not AccMove.objects.exists()

        order_line.refresh_from_db()
        assert order_line.qty_invoiced == Decimal(0)

        order.refresh_from_db()
        assert order.state == PurOrder.STATE_IN_DISPUTE
        assert order.dispute_reason
        assert str(DEFAULT_VARIANCE_THRESHOLD_PCT) in order.dispute_reason


def test_record_supplier_invoice_returns_none_without_accounting_config(
    invoicing_setup,
) -> None:
    """Aucun parametrage comptable (`_accounting_config` non appele) : le
    gap `accounting` renvoie `None`, jamais un etat FSM/`qty_invoiced`
    modifie a tort."""
    tenant, user = invoicing_setup
    with use_tenant(tenant.id):
        order = _received_order(tenant, user)
        order_line = order.lines.first()

        result = record_supplier_invoice(
            order,
            invoice_lines=[
                {
                    "order_line_id": order_line.id,
                    "qty_invoiced": Decimal(10),
                    "unit_price_mga": Decimal(1000),
                }
            ],
            date=dt.date(2026, 1, 20),
            user=user,
        )

        assert result["invoice_id"] is None
        assert result["dispute_opened"] is False

        order_line.refresh_from_db()
        assert order_line.qty_invoiced == Decimal(0)

        order.refresh_from_db()
        assert order.state == PurOrder.STATE_RECEIVED
