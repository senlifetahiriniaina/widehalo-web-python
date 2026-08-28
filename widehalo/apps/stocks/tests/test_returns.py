"""STK-RMA1 (retours client, ST6 du sous-sequencement `stocks` — cf. plan) :
cycle de vie complet `draft -> processed` (mouvement reel cree, quant
incremente a destination), annulation avant traitement, gardes de service
(refus de traiter sans evaluation prealable, refus de retraiter)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLocation, StkMove, StkReturn
from apps.stocks.services.quants import get_quant
from apps.stocks.services.returns import (
    assess_return,
    cancel_return,
    create_return,
    process_return,
)
from apps.stocks.services.warehouses import create_location, create_warehouse

pytestmark = pytest.mark.django_db


@pytest.fixture
def returns_setup():
    tenant = Tenant.objects.create(code="STK-RMA-T", name="Stocks RMA Tenant")
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-01", name="Entrepot principal")
        client_location = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="CLI",
            name="Client",
            type=StkLocation.TYPE_CLIENT,
        )
        receiving = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="RECV",
            name="Reception retours",
            type=StkLocation.TYPE_INTERNE,
        )
        return tenant, client_location, receiving


def test_full_return_flow_creates_real_move_and_increases_destination_quant(
    returns_setup,
) -> None:
    tenant, client_location, receiving = returns_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        partner_id = uuid.uuid4()
        ret = create_return(
            tenant=tenant,
            partner_id=partner_id,
            variant_id=variant_id,
            qty=Decimal("3"),
            date=dt.date(2026, 8, 1),
            reason="Taille incorrecte",
        )
        assert ret.state == StkReturn.STATE_DRAFT
        assert ret.reference

        ret = assess_return(
            ret,
            quality_state=StkReturn.QUALITY_CONFORME,
            decision=StkReturn.DECISION_REMPLACEMENT,
        )
        assert ret.state == StkReturn.STATE_DRAFT

        ret = process_return(ret, location_to=receiving)

        assert ret.state == StkReturn.STATE_PROCESSED
        assert ret.move is not None
        assert ret.move.state == StkMove.STATE_DONE
        assert ret.move.move_type == StkMove.TYPE_RETOUR
        assert ret.move.location_from_id == client_location.id
        assert ret.move.location_to_id == receiving.id

        quant = get_quant(variant_id, receiving)
        assert quant is not None
        assert quant.qty == Decimal("3")


def test_cancel_return_before_processing(returns_setup) -> None:
    tenant, _client_location, _receiving = returns_setup
    with use_tenant(tenant.id):
        ret = create_return(
            tenant=tenant,
            partner_id=uuid.uuid4(),
            variant_id=uuid.uuid4(),
            qty=Decimal("1"),
            date=dt.date(2026, 8, 1),
            reason="Erreur de commande",
        )
        ret = cancel_return(ret, reason="Client s'est retracte")
        assert ret.state == StkReturn.STATE_CANCELLED


def test_cancel_return_requires_reason(returns_setup) -> None:
    tenant, _client_location, _receiving = returns_setup
    with use_tenant(tenant.id):
        ret = create_return(
            tenant=tenant,
            partner_id=uuid.uuid4(),
            variant_id=uuid.uuid4(),
            qty=Decimal("1"),
            date=dt.date(2026, 8, 1),
            reason="Erreur de commande",
        )
        with pytest.raises(ValidationError):
            cancel_return(ret, reason="")


def test_process_return_refuses_without_assessment(returns_setup) -> None:
    tenant, _client_location, receiving = returns_setup
    with use_tenant(tenant.id):
        ret = create_return(
            tenant=tenant,
            partner_id=uuid.uuid4(),
            variant_id=uuid.uuid4(),
            qty=Decimal("1"),
            date=dt.date(2026, 8, 1),
            reason="Defaut constate",
        )
        with pytest.raises(ValidationError):
            process_return(ret, location_to=receiving)


def test_process_return_refuses_reprocessing(returns_setup) -> None:
    tenant, _client_location, receiving = returns_setup
    with use_tenant(tenant.id):
        ret = create_return(
            tenant=tenant,
            partner_id=uuid.uuid4(),
            variant_id=uuid.uuid4(),
            qty=Decimal("1"),
            date=dt.date(2026, 8, 1),
            reason="Defaut constate",
        )
        ret = assess_return(
            ret,
            quality_state=StkReturn.QUALITY_DEFAUT_MAJEUR,
            decision=StkReturn.DECISION_REFUS,
        )
        ret = process_return(ret, location_to=receiving)
        assert ret.state == StkReturn.STATE_PROCESSED

        with pytest.raises(ValidationError):
            process_return(ret, location_to=receiving)


def test_process_return_refuses_without_virtual_client_location(returns_setup) -> None:
    """`process_return` resout l'emplacement virtuel `client` DANS LE MEME
    entrepot que `location_to` (cf. docstring) — un entrepot sans
    emplacement `TYPE_CLIENT` refuse le traitement plutot que d'inventer
    une origine."""
    tenant, _client_location, _receiving = returns_setup
    with use_tenant(tenant.id):
        other_warehouse = create_warehouse(tenant=tenant, code="WH-02", name="Autre entrepot")
        other_receiving = create_location(
            tenant=tenant,
            warehouse=other_warehouse,
            code="RECV2",
            name="Reception retours 2",
            type=StkLocation.TYPE_INTERNE,
        )
        ret = create_return(
            tenant=tenant,
            partner_id=uuid.uuid4(),
            variant_id=uuid.uuid4(),
            qty=Decimal("1"),
            date=dt.date(2026, 8, 1),
            reason="Defaut constate",
        )
        ret = assess_return(
            ret,
            quality_state=StkReturn.QUALITY_CONFORME,
            decision=StkReturn.DECISION_AVOIR,
        )
        with pytest.raises(ValidationError):
            process_return(ret, location_to=other_receiving)
