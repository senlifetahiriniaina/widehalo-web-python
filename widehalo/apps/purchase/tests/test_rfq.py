from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.purchase.models import PurOrder, PurRfq
from apps.purchase.services.rfq import (
    add_rfq_line,
    add_rfq_supplier,
    award_rfq,
    compute_comparison_table,
    create_rfq,
    record_rfq_response,
    send_rfq,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def rfq_setup():
    tenant = Tenant.objects.create(code="PUR-RFQ", name="Purchase RFQ Tenant")
    with use_tenant(tenant.id):
        from apps.core.models.user import User

        user = User.objects.create_user(email="pur-rfq@example.com", password="Str0ngPassw0rd!23")
        return tenant, user


def _build_rfq(tenant):
    rfq = create_rfq(tenant=tenant, date=dt.date.today())
    variant_id = uuid.uuid4()
    add_rfq_line(rfq, variant_id=variant_id, description="Fil polyester", qty=Decimal(100))
    supplier_a = uuid.uuid4()
    supplier_b = uuid.uuid4()
    add_rfq_supplier(rfq, partner_id=supplier_a)
    add_rfq_supplier(rfq, partner_id=supplier_b)
    return rfq, variant_id, supplier_a, supplier_b


def test_create_rfq_assigns_reference(rfq_setup) -> None:
    tenant, _user = rfq_setup
    with use_tenant(tenant.id):
        rfq = create_rfq(tenant=tenant, date=dt.date.today())
        assert rfq.reference.startswith("PRFQ-")
        assert rfq.state == PurRfq.STATE_DRAFT
        assert rfq.award_criteria == {"price": 0.5, "delay": 0.3, "quality": 0.2}


def test_send_rfq_refuses_without_suppliers_or_lines(rfq_setup) -> None:
    tenant, _user = rfq_setup
    with use_tenant(tenant.id):
        rfq = create_rfq(tenant=tenant, date=dt.date.today())
        with pytest.raises(ValidationError):
            send_rfq(rfq)

        add_rfq_line(rfq, variant_id=uuid.uuid4(), description="Boutons", qty=Decimal(10))
        with pytest.raises(ValidationError):
            send_rfq(rfq)  # toujours pas de fournisseur

        add_rfq_supplier(rfq, partner_id=uuid.uuid4())
        send_rfq(rfq)
        assert rfq.state == PurRfq.STATE_SENT


def test_record_rfq_response_refuses_before_send(rfq_setup) -> None:
    tenant, _user = rfq_setup
    with use_tenant(tenant.id):
        rfq, variant_id, supplier_a, _supplier_b = _build_rfq(tenant)
        with pytest.raises(ValidationError):
            record_rfq_response(
                rfq,
                partner_id=supplier_a,
                date_received=dt.date.today(),
                lines=[
                    {"variant_id": variant_id, "qty": Decimal(100), "unit_price_mga": Decimal(1000)}
                ],
            )


def test_comparison_table_cheapest_and_fastest_wins_when_quality_neutral(rfq_setup) -> None:
    tenant, _user = rfq_setup
    with use_tenant(tenant.id):
        rfq, variant_id, supplier_a, supplier_b = _build_rfq(tenant)
        send_rfq(rfq)

        # Fournisseur A : moins cher ET plus rapide -> devrait gagner.
        response_a = record_rfq_response(
            rfq,
            partner_id=supplier_a,
            date_received=dt.date.today(),
            lines=[{"variant_id": variant_id, "qty": Decimal(100), "unit_price_mga": Decimal(900)}],
            lead_time_days=5,
        )
        response_b = record_rfq_response(
            rfq,
            partner_id=supplier_b,
            date_received=dt.date.today(),
            lines=[
                {"variant_id": variant_id, "qty": Decimal(100), "unit_price_mga": Decimal(1200)}
            ],
            lead_time_days=15,
        )

        rows = compute_comparison_table(rfq)
        assert len(rows) == 2
        assert rows[0]["response_id"] == response_a.id
        assert rows[1]["response_id"] == response_b.id
        assert rows[0]["score"] < rows[1]["score"]

        response_a.refresh_from_db()
        response_b.refresh_from_db()
        assert response_a.score is not None
        assert response_b.score is not None


def test_award_rfq_creates_real_purchase_order(rfq_setup) -> None:
    tenant, user = rfq_setup
    with use_tenant(tenant.id):
        rfq, variant_id, supplier_a, supplier_b = _build_rfq(tenant)
        send_rfq(rfq)
        response_a = record_rfq_response(
            rfq,
            partner_id=supplier_a,
            date_received=dt.date.today(),
            lines=[{"variant_id": variant_id, "qty": Decimal(100), "unit_price_mga": Decimal(900)}],
            lead_time_days=5,
        )
        record_rfq_response(
            rfq,
            partner_id=supplier_b,
            date_received=dt.date.today(),
            lines=[
                {"variant_id": variant_id, "qty": Decimal(100), "unit_price_mga": Decimal(1200)}
            ],
            lead_time_days=15,
        )

        order = award_rfq(rfq, response_a, awarded_by=user)

        assert isinstance(order, PurOrder)
        assert order.partner_id == supplier_a
        assert order.rfq_id == rfq.id
        assert order.state == PurOrder.STATE_DRAFT
        assert order.lines.count() == 1
        line = order.lines.first()
        assert line.variant_id == variant_id
        assert line.qty == Decimal(100)
        assert line.unit_price_mga == Decimal(900)
        assert line.description == "Fil polyester"
        assert order.amount_total_mga == Decimal("90000.0000")

        rfq.refresh_from_db()
        assert rfq.state == PurRfq.STATE_AWARDED


def test_award_rfq_refuses_reawarding_already_awarded_rfq(rfq_setup) -> None:
    tenant, user = rfq_setup
    with use_tenant(tenant.id):
        rfq, variant_id, supplier_a, _supplier_b = _build_rfq(tenant)
        send_rfq(rfq)
        response = record_rfq_response(
            rfq,
            partner_id=supplier_a,
            date_received=dt.date.today(),
            lines=[{"variant_id": variant_id, "qty": Decimal(100), "unit_price_mga": Decimal(900)}],
        )
        award_rfq(rfq, response, awarded_by=user)

        with pytest.raises(ValidationError):
            award_rfq(rfq, response, awarded_by=user)


def test_award_rfq_refuses_response_from_another_rfq(rfq_setup) -> None:
    tenant, user = rfq_setup
    with use_tenant(tenant.id):
        rfq_1, variant_id, supplier_a, _b = _build_rfq(tenant)
        rfq_2, _variant_id_2, supplier_c, _d = _build_rfq(tenant)
        send_rfq(rfq_1)
        send_rfq(rfq_2)
        response_from_rfq_2 = record_rfq_response(
            rfq_2,
            partner_id=supplier_c,
            date_received=dt.date.today(),
            lines=[{"variant_id": variant_id, "qty": Decimal(10), "unit_price_mga": Decimal(500)}],
        )
        with pytest.raises(ValidationError):
            award_rfq(rfq_1, response_from_rfq_2, awarded_by=user)
