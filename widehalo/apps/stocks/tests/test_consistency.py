"""RG-STK-6 (cohérence production/stock, ST6 du sous-sequencement `stocks`
— cf. plan) : `production_consistency_report`, acceptance test §5.8.7 n°4
explicitement exerce (OF declarant 100, 95 entrees en stock -> anomalie
avec `variance=-5`)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.mrp.models import MrpOrder
from apps.mrp.tests.factories import MrpOrderFactory
from apps.stocks.models import StkLocation, StkMove
from apps.stocks.services.consistency import production_consistency_report
from apps.stocks.services.moves import create_move, validate_move
from apps.stocks.services.warehouses import create_location, create_warehouse

pytestmark = pytest.mark.django_db


@pytest.fixture
def consistency_setup():
    tenant = Tenant.objects.create(code="STK-COHER-T", name="Stocks Coherence Tenant")
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-01", name="Entrepot principal")
        production = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="PROD",
            name="Production",
            type=StkLocation.TYPE_PRODUCTION,
        )
        internal = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="A1",
            name="Rayon A1",
            type=StkLocation.TYPE_INTERNE,
        )
        return tenant, production, internal


def _enter_production_stock(
    tenant, production, internal, *, variant_id, qty, source_document, date
):
    move = create_move(
        tenant=tenant,
        variant_id=variant_id,
        qty=qty,
        uom="pc",
        location_from=production,
        location_to=internal,
        date=date,
        move_type=StkMove.TYPE_PRODUCTION_IN,
        source_document=source_document,
        unit_cost_mga=Decimal("10"),
    )
    return validate_move(move)


def test_production_consistency_report_flags_acceptance_test_case(consistency_setup) -> None:
    """Acceptance test §5.8.7 n°4 (CDC, litteral) : un OF declarant 100
    pieces avec seulement 95 entrees en stock apparait dans le rapport de
    coherence, `anomaly=True`, `variance=-5` (entre en stock - declare)."""
    tenant, production, internal = consistency_setup
    with use_tenant(tenant.id):
        order = MrpOrderFactory(
            tenant=tenant,
            state=MrpOrder.STATE_CLOSED,
            qty=Decimal("100"),
            qty_produced=Decimal("100"),
        )
        _enter_production_stock(
            tenant,
            production,
            internal,
            variant_id=order.variant_id,
            qty=Decimal("95"),
            source_document=order.reference,
            date=dt.date(2026, 8, 1),
        )

        report = production_consistency_report(tenant, since=dt.date(2026, 1, 1))
        row = next(r for r in report if r["order_id"] == order.id)

        assert row["order_reference"] == order.reference
        assert row["qty_declared"] == Decimal("100")
        assert row["qty_entered_stock"] == Decimal("95.0000")
        assert row["variance"] == Decimal("-5.0000")
        assert row["anomaly"] is True


def test_production_consistency_report_no_anomaly_when_quantities_match(consistency_setup) -> None:
    tenant, production, internal = consistency_setup
    with use_tenant(tenant.id):
        order = MrpOrderFactory(
            tenant=tenant,
            state=MrpOrder.STATE_CLOSED,
            qty=Decimal("50"),
            qty_produced=Decimal("50"),
        )
        _enter_production_stock(
            tenant,
            production,
            internal,
            variant_id=order.variant_id,
            qty=Decimal("50"),
            source_document=order.reference,
            date=dt.date(2026, 8, 1),
        )

        report = production_consistency_report(tenant, since=dt.date(2026, 1, 1))
        row = next(r for r in report if r["order_id"] == order.id)

        assert row["qty_declared"] == Decimal("50")
        assert row["qty_entered_stock"] == Decimal("50.0000")
        assert row["variance"] == Decimal("0.0000")
        assert row["anomaly"] is False


def test_production_consistency_report_lists_all_closed_orders_in_window(consistency_setup) -> None:
    """Choix retenu : le rapport liste TOUS les ordres clotures de la
    fenetre, anomalie ou non (cf. docstring `production_consistency_report`)
    — un ordre sans aucune entree en stock apparait donc aussi, avec
    `qty_entered_stock=0` et `anomaly=True` des lors que `qty_declared>0`."""
    tenant, production, internal = consistency_setup
    with use_tenant(tenant.id):
        order = MrpOrderFactory(
            tenant=tenant,
            state=MrpOrder.STATE_CLOSED,
            qty=Decimal("10"),
            qty_produced=Decimal("10"),
        )
        report = production_consistency_report(tenant, since=dt.date(2026, 1, 1))
        row = next(r for r in report if r["order_id"] == order.id)
        assert row["qty_entered_stock"] == Decimal(0)
        assert row["anomaly"] is True


def test_production_consistency_report_excludes_orders_outside_window(consistency_setup) -> None:
    tenant, production, internal = consistency_setup
    with use_tenant(tenant.id):
        order = MrpOrderFactory(tenant=tenant, state=MrpOrder.STATE_CLOSED)
        # `.update()` (pas `.save()`) : `updated_at` est `auto_now=True`,
        # `Model.save()` l'ecraserait systematiquement avec l'heure
        # courante meme si on l'assigne explicitement avant — seul un
        # UPDATE SQL direct (`QuerySet.update()`, qui ne passe jamais par
        # `Field.pre_save`) permet de simuler une date passee dans ce test.
        MrpOrder.objects.filter(id=order.id).update(
            updated_at=dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
        )

        report = production_consistency_report(tenant, since=dt.date(2026, 1, 1))
        assert order.id not in {r["order_id"] for r in report}


def test_production_consistency_report_excludes_non_closed_orders(consistency_setup) -> None:
    tenant, production, internal = consistency_setup
    with use_tenant(tenant.id):
        order = MrpOrderFactory(tenant=tenant, state=MrpOrder.STATE_DRAFT)
        report = production_consistency_report(tenant, since=dt.date(2026, 1, 1))
        assert order.id not in {r["order_id"] for r in report}
