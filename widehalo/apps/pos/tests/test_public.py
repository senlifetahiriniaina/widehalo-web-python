"""Tests du contrat public de `pos` (`apps/pos/services/public.py`)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.pos.models import PosOrderLine, PosSession
from apps.pos.services.orders import add_line, add_payment, create_draft_order, validate_order
from apps.pos.services.public import get_session_cash_summary, list_open_sessions
from apps.pos.services.sessions import open_session
from apps.pos.tests.factories import PosPaymentMethodFactory, PosRegisterFactory, PosSessionFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    t = Tenant.objects.create(code="POS-PUB", name="POS Public Tenant")
    with use_tenant(t.id):
        yield t


def test_list_open_sessions_returns_only_open_sessions_as_primitives(tenant) -> None:
    register = PosRegisterFactory(tenant=tenant)
    open_sess = PosSessionFactory(tenant=tenant, register=register)
    closed_sess = PosSessionFactory(tenant=tenant, register=PosRegisterFactory(tenant=tenant))
    closed_sess.state = PosSession.STATE_CLOSED
    closed_sess.save(update_fields=["state"])

    result = list_open_sessions(tenant)

    assert [row["id"] for row in result] == [str(open_sess.id)]
    assert all(isinstance(row, dict) for row in result)


def test_get_session_cash_summary_returns_none_for_an_unknown_session(tenant) -> None:
    assert get_session_cash_summary(uuid.uuid4()) is None


def test_get_session_cash_summary_reports_payments_by_method_and_pending_offline_orders(
    tenant,
) -> None:
    session = PosSessionFactory(tenant=tenant)
    cash = PosPaymentMethodFactory(tenant=tenant, type="cash")

    order = create_draft_order(tenant, session=session, client_uuid=uuid.uuid4(), local_sequence=1)
    add_line(
        order, line_type=PosOrderLine.TYPE_SERVICE, description="Service", qty=Decimal(1), unit_price=Decimal(1000)
    )
    order.refresh_from_db()
    add_payment(order, method=cash, amount=order.amount_total)
    validate_order(order, date=dt.date(2026, 1, 15))

    from apps.pos.models import PosOrder

    PosOrder.objects.create(
        tenant=tenant,
        session=session,
        register=session.register,
        client_uuid=uuid.uuid4(),
        local_sequence=2,
        state=PosOrder.STATE_DRAFT,
        source=PosOrder.SOURCE_OFFLINE,
    )

    summary = get_session_cash_summary(session.id)

    assert summary is not None
    assert summary["register_code"] == session.register.code
    assert summary["payments_by_method"] == [{"method": cash.name, "total": Decimal(1000)}]
    assert summary["pending_offline_orders"] == 1
