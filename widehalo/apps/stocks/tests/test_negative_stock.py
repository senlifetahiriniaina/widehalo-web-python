"""RG-STK-10 (stock negatif, ST7 du sous-sequencement `stocks` — cf.
plan) : interdiction par defaut d'un mouvement sortant depuis un
emplacement interne qui ferait passer un quant negatif, exception par
produit (journalisee + alerte), revocation, et non-regression explicite
sur le comportement des emplacements virtuels (ST2 — vont legitimement
negatif, jamais concernes par cette garde)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.audit import AuditLog
from apps.core.models.notification import Notification
from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLocation, StkMove, StkNegativeStockException
from apps.stocks.services.moves import create_move, validate_move
from apps.stocks.services.negative_stock import (
    grant_negative_stock_exception,
    has_negative_stock_exception,
    revoke_negative_stock_exception,
)
from apps.stocks.services.warehouses import create_location, create_warehouse

pytestmark = pytest.mark.django_db


@pytest.fixture
def negative_stock_setup():
    tenant = Tenant.objects.create(code="STK-NEG-T", name="Stocks Negative Stock Tenant")
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-01", name="Entrepot principal")
        internal = create_location(
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
        client = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="CLI",
            name="Client",
            type=StkLocation.TYPE_CLIENT,
        )
        variant_id = uuid.uuid4()
        operator = UserFactory()
        authorizer = UserFactory()
    return tenant, internal, supplier, client, variant_id, operator, authorizer


def _outbound_move(
    *, tenant, internal, client, variant_id, qty, operator=None, date=None
) -> StkMove:
    return create_move(
        tenant=tenant,
        variant_id=variant_id,
        qty=qty,
        uom="pc",
        location_from=internal,
        location_to=client,
        date=date or dt.date.today(),
        move_type=StkMove.TYPE_LIVRAISON,
        unit_cost_mga=Decimal("100"),
        operator=operator,
    )


def test_outbound_move_from_empty_internal_location_refused_by_default(
    negative_stock_setup,
) -> None:
    tenant, internal, _supplier, client, variant_id, _operator, _authorizer = negative_stock_setup
    with use_tenant(tenant.id):
        move = _outbound_move(
            tenant=tenant, internal=internal, client=client, variant_id=variant_id, qty=Decimal("5")
        )
        with pytest.raises(ValidationError):
            validate_move(move)


def test_outbound_move_allowed_once_exception_granted(negative_stock_setup) -> None:
    tenant, internal, _supplier, client, variant_id, operator, authorizer = negative_stock_setup
    with use_tenant(tenant.id):
        grant_negative_stock_exception(
            tenant=tenant,
            variant_id=variant_id,
            authorized_by=authorizer,
            reason="Rupture temporaire acceptee par le responsable stock",
        )
        assert has_negative_stock_exception(variant_id) is True

        move = _outbound_move(
            tenant=tenant,
            internal=internal,
            client=client,
            variant_id=variant_id,
            qty=Decimal("5"),
            operator=operator,
        )
        validate_move(move)
        assert move.state == StkMove.STATE_DONE


def test_exception_use_is_journalized(negative_stock_setup) -> None:
    tenant, internal, _supplier, client, variant_id, operator, authorizer = negative_stock_setup
    with use_tenant(tenant.id):
        grant_negative_stock_exception(
            tenant=tenant, variant_id=variant_id, authorized_by=authorizer, reason="Motif"
        )
        move = _outbound_move(
            tenant=tenant,
            internal=internal,
            client=client,
            variant_id=variant_id,
            qty=Decimal("3"),
            operator=operator,
        )
        validate_move(move)

        logs = AuditLog.objects.filter(action="stocks.negative_stock.used", object_id=str(move.id))
        assert logs.count() == 1
        assert logs.first().actor_id == operator.id


def test_exception_use_triggers_alert_to_operator(negative_stock_setup) -> None:
    tenant, internal, _supplier, client, variant_id, operator, authorizer = negative_stock_setup
    with use_tenant(tenant.id):
        grant_negative_stock_exception(
            tenant=tenant, variant_id=variant_id, authorized_by=authorizer, reason="Motif"
        )
        move = _outbound_move(
            tenant=tenant,
            internal=internal,
            client=client,
            variant_id=variant_id,
            qty=Decimal("3"),
            operator=operator,
        )
        validate_move(move)

        notifications = Notification.objects.filter(
            user=operator, notification_type="stocks.negative_stock_used"
        )
        assert notifications.count() == 1
        assert notifications.first().payload["move_id"] == str(move.id)


def test_exception_use_without_operator_is_journalized_but_not_notified(
    negative_stock_setup,
) -> None:
    tenant, internal, _supplier, client, variant_id, _operator, authorizer = negative_stock_setup
    with use_tenant(tenant.id):
        grant_negative_stock_exception(
            tenant=tenant, variant_id=variant_id, authorized_by=authorizer, reason="Motif"
        )
        move = _outbound_move(
            tenant=tenant, internal=internal, client=client, variant_id=variant_id, qty=Decimal("3")
        )
        validate_move(move)

        assert AuditLog.objects.filter(
            action="stocks.negative_stock.used", object_id=str(move.id)
        ).exists()
        assert not Notification.objects.filter(
            notification_type="stocks.negative_stock_used"
        ).exists()


def test_revoked_exception_re_blocks_negative_stock(negative_stock_setup) -> None:
    tenant, internal, _supplier, client, variant_id, _operator, authorizer = negative_stock_setup
    with use_tenant(tenant.id):
        exception = grant_negative_stock_exception(
            tenant=tenant, variant_id=variant_id, authorized_by=authorizer, reason="Motif"
        )
        revoke_negative_stock_exception(exception)
        assert has_negative_stock_exception(variant_id) is False

        move = _outbound_move(
            tenant=tenant, internal=internal, client=client, variant_id=variant_id, qty=Decimal("2")
        )
        with pytest.raises(ValidationError):
            validate_move(move)


def test_grant_reactivates_revoked_exception_rather_than_duplicating(
    negative_stock_setup,
) -> None:
    tenant, _internal, _supplier, _client, variant_id, _operator, authorizer = negative_stock_setup
    with use_tenant(tenant.id):
        first = grant_negative_stock_exception(
            tenant=tenant, variant_id=variant_id, authorized_by=authorizer, reason="Premier motif"
        )
        revoke_negative_stock_exception(first)

        second = grant_negative_stock_exception(
            tenant=tenant, variant_id=variant_id, authorized_by=authorizer, reason="Second motif"
        )
        assert second.id == first.id
        assert second.is_active is True
        assert second.reason == "Second motif"
        assert (
            StkNegativeStockException.all_objects.filter(
                tenant=tenant, variant_id=variant_id
            ).count()
            == 1
        )


def test_grant_refuses_when_exception_already_active(negative_stock_setup) -> None:
    tenant, _internal, _supplier, _client, variant_id, _operator, authorizer = negative_stock_setup
    with use_tenant(tenant.id):
        grant_negative_stock_exception(
            tenant=tenant, variant_id=variant_id, authorized_by=authorizer, reason="Motif"
        )
        with pytest.raises(ValidationError):
            grant_negative_stock_exception(
                tenant=tenant, variant_id=variant_id, authorized_by=authorizer, reason="Autre motif"
            )


def test_virtual_locations_remain_unaffected_by_negative_stock_guard(
    negative_stock_setup,
) -> None:
    """Non-regression ST2 : une reception (source `fournisseur`, emplacement
    virtuel) fait legitimement passer le quant virtuel en negatif — jamais
    concernee par la garde RG-STK-10 (qui ne porte que sur les sources
    `_is_valuation_internal`, cf. `services/moves.py`)."""
    tenant, internal, supplier, _client, variant_id, _operator, _authorizer = negative_stock_setup
    with use_tenant(tenant.id):
        move = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal("10"),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date.today(),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost_mga=Decimal("100"),
        )
        validate_move(move)

        from apps.stocks.services.quants import get_quant

        supplier_quant = get_quant(variant_id, supplier)
        assert supplier_quant is not None
        assert supplier_quant.qty == Decimal("-10")
