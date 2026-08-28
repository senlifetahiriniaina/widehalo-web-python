from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounting.models import AccAccount, AccJournal
from apps.accounting.tests.factories import AccAccountFactory, AccJournalFactory, AccPeriodFactory
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.logistics.models import LogCustomsFile
from apps.logistics.services.customs import (
    add_customs_line,
    close_customs_file,
    create_customs_file,
    create_hs_code,
    mark_customs_file_cleared,
    report_shipment_delay,
    simulate_customs_duties,
)
from apps.logistics.services.shipments import create_shipment
from apps.purchase.models import PurCri
from apps.stocks.models import StkLocation, StkValuationLayer, StkWarehouse
from apps.stocks.services.moves import create_move, validate_move

pytestmark = pytest.mark.django_db


@pytest.fixture
def customs_setup():
    tenant = Tenant.objects.create(code="LOG-DOU-T", name="Logistics Customs Tenant")
    with use_tenant(tenant.id):
        shipment = create_shipment(tenant, origin="Guangzhou", destination="Toamasina")
        hs_code = create_hs_code(
            tenant, code="6109.1000", description="T-shirts en coton", duty_rate_pct=Decimal("20")
        )
        return tenant, shipment, hs_code


def test_simulate_customs_duties_matches_hand_computed_formula() -> None:
    result = simulate_customs_duties(
        fob_value_mga=Decimal("1000000"),
        duty_rate_pct=Decimal("20"),
        freight_value_mga=Decimal("100000"),
        insurance_value_mga=Decimal("50000"),
        other_non_recoverable_taxes_mga=Decimal("10000"),
        transit_cost_mga=Decimal("30000"),
    )
    # CAF = 1 000 000 + 100 000 + 50 000 = 1 150 000
    assert result["caf_value_mga"] == Decimal("1150000")
    # Droits = CAF x 20% = 230 000
    assert result["duty_mga"] == Decimal("230000")
    # Base TVA = CAF + Droits + autres taxes = 1 150 000 + 230 000 + 10 000 = 1 390 000
    assert result["vat_base_mga"] == Decimal("1390000")
    # TVA = Base TVA x 20% = 278 000
    assert result["vat_mga"] == Decimal("278000")
    # Cout de revient = FOB+Fret+Assurance+Droits+autres taxes+Transit
    # = 1 000 000+100 000+50 000+230 000+10 000+30 000 = 1 420 000
    assert result["landed_cost_mga"] == Decimal("1420000")


def test_add_customs_line_persists_computed_amounts(customs_setup) -> None:
    tenant, shipment, hs_code = customs_setup
    with use_tenant(tenant.id):
        customs_file = create_customs_file(tenant, shipment=shipment)
        line = add_customs_line(
            customs_file,
            hs_code=hs_code,
            description="Lot de t-shirts",
            fob_value_mga=Decimal("1000000"),
            freight_value_mga=Decimal("100000"),
        )
        assert line.duty_mga == Decimal("220000")  # (1 000 000+100 000) x 20%


def test_close_customs_file_requires_cleared_state(customs_setup) -> None:
    tenant, shipment, hs_code = customs_setup
    with use_tenant(tenant.id):
        customs_file = create_customs_file(tenant, shipment=shipment)
        add_customs_line(
            customs_file, hs_code=hs_code, description="Lot", fob_value_mga=Decimal("500000")
        )
        with pytest.raises(ValidationError):
            close_customs_file(customs_file)


def test_close_customs_file_transfers_cost_and_updates_valuation(customs_setup) -> None:
    tenant, shipment, hs_code = customs_setup
    with use_tenant(tenant.id):
        AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_PURCHASE)
        AccPeriodFactory(
            tenant=tenant, date_start=dt.date(2026, 1, 1), date_end=dt.date(2026, 1, 31)
        )
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_PAYABLE)
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_STOCK)

        warehouse = StkWarehouse.objects.create(tenant=tenant, code="WH1", name="Entrepot")
        supplier_location = StkLocation.objects.create(
            tenant=tenant, warehouse=warehouse, code="FOUR", name="Fournisseur", type="fournisseur"
        )
        stock_location = StkLocation.objects.create(
            tenant=tenant, warehouse=warehouse, code="STK", name="Stock", type="interne"
        )
        variant_id = uuid.uuid4()
        move = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal("100"),
            uom="PC",
            location_from=supplier_location,
            location_to=stock_location,
            date=dt.date(2026, 1, 5),
            move_type="reception",
            unit_cost_mga=Decimal("10000"),
        )
        validate_move(move)

        customs_file = create_customs_file(tenant, shipment=shipment)
        add_customs_line(
            customs_file,
            hs_code=hs_code,
            description="Lot",
            fob_value_mga=Decimal("1000000"),
            variant_id=variant_id,
            qty=Decimal("100"),
        )
        mark_customs_file_cleared(customs_file)
        closed = close_customs_file(customs_file)

        assert closed.state == LogCustomsFile.STATE_CLOSED
        assert closed.landed_cost_batch_id is not None

        layer = StkValuationLayer.objects.get(move=move)
        # Valeur initiale 100 x 10 000 = 1 000 000, + droits (200 000) = 1 200 000
        assert layer.value_mga == Decimal("1200000")


def test_report_shipment_delay_returns_none_before_threshold(customs_setup) -> None:
    tenant, shipment, _hs_code = customs_setup
    with use_tenant(tenant.id):
        result = report_shipment_delay(
            shipment,
            expected_date=dt.date(2026, 1, 1),
            supplier_partner_id=uuid.uuid4(),
            as_of=dt.date(2026, 1, 2),
        )
        assert result is None


def test_report_shipment_delay_opens_incident_past_threshold(customs_setup) -> None:
    tenant, shipment, _hs_code = customs_setup
    with use_tenant(tenant.id):
        partner_id = uuid.uuid4()
        cri_id = report_shipment_delay(
            shipment,
            expected_date=dt.date(2026, 1, 1),
            supplier_partner_id=partner_id,
            as_of=dt.date(2026, 1, 10),
        )
        assert cri_id is not None
        cri = PurCri.objects.get(id=cri_id)
        assert cri.type == PurCri.TYPE_RETARD
        assert cri.partner_id == partner_id
