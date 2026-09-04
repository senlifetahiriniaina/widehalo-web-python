"""Session de caisse (POS-2, POS-6, POS-7, POS-9)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError

from apps.accounting.models import AccAccount, AccJournal, AccMove
from apps.accounting.tests.factories import AccAccountFactory, AccJournalFactory, AccPeriodFactory
from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.pos.models import PosCashMovement, PosOrderLine, PosPaymentMethod, PosSession
from apps.pos.services.orders import add_line, add_payment, create_draft_order, validate_order
from apps.pos.services.sessions import (
    add_cash_movement,
    close_session,
    compute_expected_cash,
    open_session,
)
from apps.pos.tests.factories import PosPaymentMethodFactory, PosRegisterFactory, PosSessionFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    t = Tenant.objects.create(code="POS-SESS", name="POS Sessions Tenant")
    with use_tenant(t.id):
        yield t


def _accounting_setup(tenant: Tenant) -> None:
    AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_CASH)
    AccPeriodFactory(tenant=tenant, date_start=dt.date(2026, 1, 1), date_end=dt.date(2026, 1, 31))
    AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_CASH)
    AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_INCOME)
    AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_TAX)
    AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_EXPENSE)


def _cash_method(tenant: Tenant) -> PosPaymentMethod:
    return PosPaymentMethodFactory(
        tenant=tenant,
        type=PosPaymentMethod.TYPE_CASH,
        default_account_type=PosPaymentMethod.ACCOUNT_TYPE_CASH,
    )


def test_open_session_refuses_a_second_open_session_on_the_same_register(tenant) -> None:
    register = PosRegisterFactory(tenant=tenant)
    cashier = UserFactory()
    open_session(tenant, register=register, cashier=cashier, opening_cash_amount=Decimal(10000))

    with pytest.raises(ValidationError):
        open_session(tenant, register=register, cashier=cashier)


def test_add_cash_movement_requires_a_reason_and_an_open_session(tenant) -> None:
    session = PosSessionFactory(tenant=tenant)
    with pytest.raises(ValidationError):
        add_cash_movement(
            session, direction=PosCashMovement.DIRECTION_IN, amount=Decimal(1000), reason=""
        )

    session.state = PosSession.STATE_CLOSED
    session.save(update_fields=["state"])
    with pytest.raises(ValidationError):
        add_cash_movement(
            session, direction=PosCashMovement.DIRECTION_IN, amount=Decimal(1000), reason="Appoint"
        )


def test_compute_expected_cash_includes_opening_amount_movements_and_cash_sales(tenant) -> None:
    session = PosSessionFactory(tenant=tenant, opening_cash_amount=Decimal(50000))
    cash_method = _cash_method(tenant)

    add_cash_movement(
        session, direction=PosCashMovement.DIRECTION_IN, amount=Decimal(5000), reason="Dépôt"
    )
    add_cash_movement(
        session, direction=PosCashMovement.DIRECTION_OUT, amount=Decimal(2000), reason="Retrait"
    )

    order = create_draft_order(
        tenant, session=session, client_uuid=uuid.uuid4(), local_sequence=1, user=session.cashier
    )
    add_line(
        order,
        line_type=PosOrderLine.TYPE_SERVICE,
        description="Prestation",
        qty=Decimal(1),
        unit_price=Decimal(10000),
    )
    order.refresh_from_db()
    add_payment(order, method=cash_method, amount=order.amount_total, user=session.cashier)
    validate_order(order, user=session.cashier, date=dt.date(2026, 1, 15))

    expected = compute_expected_cash(session)
    # 50000 (ouverture) + 5000 (entrée) - 2000 (sortie) + 10000 (vente espèces)
    assert expected == Decimal(50000 + 5000 - 2000 + 10000)


def test_close_session_requires_a_reason_when_there_is_a_variance(tenant) -> None:
    _accounting_setup(tenant)
    session = PosSessionFactory(tenant=tenant, opening_cash_amount=Decimal(10000))
    with pytest.raises(ValidationError):
        close_session(session, counted_cash=Decimal(9000), variance_reason="")


def test_close_session_generates_a_balanced_accounting_entry_and_locks_the_session(tenant) -> None:
    _accounting_setup(tenant)
    session = PosSessionFactory(tenant=tenant, opening_cash_amount=Decimal(0))
    cash_method = _cash_method(tenant)

    order = create_draft_order(
        tenant, session=session, client_uuid=uuid.uuid4(), local_sequence=1, user=session.cashier
    )
    add_line(
        order,
        line_type=PosOrderLine.TYPE_SERVICE,
        description="Prestation",
        qty=Decimal(1),
        unit_price=Decimal(10000),
    )
    order.refresh_from_db()
    add_payment(order, method=cash_method, amount=order.amount_total, user=session.cashier)
    validate_order(order, user=session.cashier, date=dt.date(2026, 1, 15))
    order.refresh_from_db()

    expected_cash = compute_expected_cash(session)
    counted = expected_cash - Decimal(500)  # écart : manquant en caisse
    closed = close_session(
        session,
        counted_cash=counted,
        variance_reason="Erreur de rendu de monnaie",
        date=dt.date(2026, 1, 15),
    )

    assert closed.state == PosSession.STATE_CLOSED
    assert closed.cash_variance == Decimal(-500)
    assert closed.closing_move_id is not None

    move = AccMove.objects.get(id=closed.closing_move_id)
    assert move.state == AccMove.STATE_POSTED
    total_debit = sum((line.debit for line in move.lines.all()), Decimal(0))
    total_credit = sum((line.credit for line in move.lines.all()), Decimal(0))
    assert total_debit == total_credit  # RG-ACC-1 : écriture équilibrée

    # POS-9 : session close immuable.
    with pytest.raises(ValidationError):
        add_cash_movement(
            session, direction=PosCashMovement.DIRECTION_IN, amount=Decimal(1), reason="x"
        )
    with pytest.raises(ValidationError):
        close_session(session, counted_cash=Decimal(0))


def test_only_the_session_owner_or_a_transverse_role_can_manage_it(tenant) -> None:
    session = PosSessionFactory(tenant=tenant)
    stranger = UserFactory()

    with pytest.raises(PermissionDenied):
        add_cash_movement(
            session,
            direction=PosCashMovement.DIRECTION_IN,
            amount=Decimal(100),
            reason="x",
            user=stranger,
        )

    admin_group, _ = Group.objects.get_or_create(name="admin")
    stranger.groups.add(admin_group)
    # Ne lève plus PermissionDenied (admin = pilotage transverse).
    add_cash_movement(
        session,
        direction=PosCashMovement.DIRECTION_IN,
        amount=Decimal(100),
        reason="Contrôle admin",
        user=stranger,
    )
    assert PosCashMovement.objects.filter(session=session).count() == 1
