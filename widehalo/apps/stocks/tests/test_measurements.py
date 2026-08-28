"""RG-STK-4 (mesures physiques, ST3 du sous-sequencement `stocks` — cf.
plan) : calcul d'ecart, ouverture automatique d'un litige fournisseur
au-dela du seuil, delegation de la conversion m/kg (RG-STK-5)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.purchase.models import PurCri
from apps.stocks.models import StkLocation, StkMeasurement
from apps.stocks.services.measurements import (
    DEFAULT_VARIANCE_THRESHOLD_PCT,
    convert_measurement,
    create_reception_move_from_measurement,
    record_measurement,
)
from apps.stocks.services.moves import validate_move
from apps.stocks.services.quants import on_hand_qty
from apps.stocks.services.warehouses import create_location, create_warehouse

pytestmark = pytest.mark.django_db


@pytest.fixture
def measurement_setup():
    tenant = Tenant.objects.create(code="STK-MEAS-T", name="Stocks Measurements Tenant")
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
        return tenant, internal, supplier


def test_record_measurement_computes_variance_pct_against_theoretical(measurement_setup) -> None:
    tenant, _internal, _supplier = measurement_setup
    with use_tenant(tenant.id):
        measurement = record_measurement(
            tenant=tenant,
            type=StkMeasurement.TYPE_LONGUEUR,
            value=Decimal("98"),
            uom="m",
            theoretical_value=Decimal("100"),
        )
        assert measurement.value == Decimal("98")
        # |98 - 100| / 100 * 100 = 2%.
        assert measurement.variance_pct == Decimal("2")


def test_record_measurement_without_theoretical_leaves_variance_none(measurement_setup) -> None:
    tenant, _internal, _supplier = measurement_setup
    with use_tenant(tenant.id):
        measurement = record_measurement(
            tenant=tenant, type=StkMeasurement.TYPE_POIDS, value=Decimal("50"), uom="kg"
        )
        assert measurement.variance_pct is None


def test_record_measurement_guards_zero_theoretical(measurement_setup) -> None:
    tenant, _internal, _supplier = measurement_setup
    with use_tenant(tenant.id):
        measurement = record_measurement(
            tenant=tenant,
            type=StkMeasurement.TYPE_POIDS,
            value=Decimal("5"),
            uom="kg",
            theoretical_value=Decimal("0"),
        )
        assert measurement.variance_pct is None


def test_record_measurement_below_threshold_opens_no_dispute(measurement_setup) -> None:
    tenant, _internal, _supplier = measurement_setup
    with use_tenant(tenant.id):
        partner_id = uuid.uuid4()
        record_measurement(
            tenant=tenant,
            type=StkMeasurement.TYPE_LONGUEUR,
            value=Decimal("99"),
            uom="m",
            theoretical_value=Decimal("100"),
            partner_id_for_dispute=partner_id,
        )
        assert not PurCri.objects.filter(partner_id=partner_id).exists()


def test_record_measurement_without_partner_id_never_opens_a_dispute_even_above_threshold(
    measurement_setup,
) -> None:
    """Meme au-dela du seuil, aucun litige n'est ouvert si l'appelant ne
    fournit pas `partner_id_for_dispute` (contexte sans fournisseur
    identifiable, ex. recomptage d'inventaire interne)."""
    tenant, _internal, _supplier = measurement_setup
    with use_tenant(tenant.id):
        record_measurement(
            tenant=tenant,
            type=StkMeasurement.TYPE_LONGUEUR,
            value=Decimal("47.5"),
            uom="m",
            theoretical_value=Decimal("50"),
        )
        assert not PurCri.objects.exists()


def test_record_measurement_acceptance_case_50m_announced_47_5m_measured_opens_dispute(
    measurement_setup,
) -> None:
    """Acceptance test §5.8.7 n°3 (CDC) : rouleau annonce a 50m, mesure a
    47.5m -> ecart de 5% (> seuil 3% par defaut) -> la mesure enregistree
    reste 47.5m (jamais 50m) et un litige fournisseur est ouvert
    automatiquement.

    Calcul a la main : |47.5 - 50| / 50 * 100 = 2.5 / 50 * 100 = 5%."""
    tenant, _internal, _supplier = measurement_setup
    with use_tenant(tenant.id):
        partner_id = uuid.uuid4()
        measurement = record_measurement(
            tenant=tenant,
            type=StkMeasurement.TYPE_LONGUEUR,
            value=Decimal("47.5"),
            uom="m",
            theoretical_value=Decimal("50"),
            partner_id_for_dispute=partner_id,
        )

        assert measurement.value == Decimal("47.5")
        assert measurement.variance_pct == Decimal("5")
        assert measurement.variance_pct > DEFAULT_VARIANCE_THRESHOLD_PCT

        cri = PurCri.objects.get(partner_id=partner_id)
        assert cri.type == PurCri.TYPE_NON_CONFORMITE
        assert cri.state == PurCri.STATE_DRAFT


def test_record_measurement_respects_custom_threshold(measurement_setup) -> None:
    tenant, _internal, _supplier = measurement_setup
    with use_tenant(tenant.id):
        partner_id = uuid.uuid4()
        # Ecart de 2% (98 vs 100) : sous le seuil par defaut (3%) mais
        # au-dela d'un seuil personnalise plus strict (1%).
        record_measurement(
            tenant=tenant,
            type=StkMeasurement.TYPE_LONGUEUR,
            value=Decimal("98"),
            uom="m",
            theoretical_value=Decimal("100"),
            threshold_pct=Decimal("1"),
            partner_id_for_dispute=partner_id,
        )
        assert PurCri.objects.filter(partner_id=partner_id).exists()


def test_convert_measurement_returns_none_without_textile_spec(measurement_setup) -> None:
    tenant, _internal, _supplier = measurement_setup
    with use_tenant(tenant.id):
        assert convert_measurement(uuid.uuid4(), length_m=Decimal("10")) is None


def test_convert_measurement_refuses_both_or_neither(measurement_setup) -> None:
    tenant, _internal, _supplier = measurement_setup
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        convert_measurement(uuid.uuid4())


def test_create_reception_move_from_measurement_derives_qty_from_measurement_value(
    measurement_setup,
) -> None:
    """RG-STK-4 : "la quantite en stock retenue est la quantite MESUREE,
    jamais la theorique" — cette enveloppe de convenance rend ce
    comportement automatique : `qty` provient toujours de
    `measurement.value`, jamais d'un chiffre theorique transmis a part."""
    tenant, internal, supplier = measurement_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        measurement = record_measurement(
            tenant=tenant,
            type=StkMeasurement.TYPE_LONGUEUR,
            value=Decimal("47.5"),
            uom="m",
            theoretical_value=Decimal("50"),
        )
        move = create_reception_move_from_measurement(
            measurement,
            tenant=tenant,
            variant_id=variant_id,
            location_from=supplier,
            location_to=internal,
            date=dt.date.today(),
            unit_cost_mga=Decimal("1000"),
        )
        assert move.qty == Decimal("47.5")
        assert move.uom == "m"

        validate_move(move)
        assert on_hand_qty(variant_id) == Decimal("47.5")
