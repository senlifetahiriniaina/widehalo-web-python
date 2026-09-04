"""Bloc D, D1 (QUA-1/2/3) : `record_measurement` — une mesure hors limites
ouvre une non-conformité ET bloque le lot concerné, dans la même
transaction."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.quality.models import QltNonConformity
from apps.quality.services.control_plans import add_critical_point, create_control_plan
from apps.quality.services.measurements import record_measurement
from apps.quality.services.non_conformity import close_non_conformity
from apps.quality.services.public import release_lot_hold
from apps.stocks.models import StkLot
from apps.stocks.tests.factories import StkLotFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def measurement_setup():
    tenant = Tenant.objects.create(code="QLT-MEAS", name="Quality Measurement Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="qlt@example.com", password="Str0ngPassw0rd!23")
        plan = create_control_plan(tenant=tenant, name="Cuisson", frequency_days=1)
        critical_point = add_critical_point(
            plan, name="Température", unit="°C", limit_min=Decimal(70), limit_max=Decimal(90)
        )
        lot = StkLotFactory(tenant=tenant, name="LOT-QLT-001")
        return tenant, user, critical_point, lot


def test_record_measurement_within_limits_does_not_open_non_conformity(measurement_setup) -> None:
    tenant, user, critical_point, lot = measurement_setup
    with use_tenant(tenant.id):
        measurement = record_measurement(
            critical_point,
            tenant=tenant,
            value=Decimal(80),
            measured_by=user,
            lot_variant_id=lot.variant_id,
            lot_name=lot.name,
        )
        assert measurement.is_within_limits is True
        assert QltNonConformity.objects.filter(tenant=tenant).count() == 0

        lot.refresh_from_db()
        assert lot.is_held() is False


def test_record_measurement_outside_limits_opens_non_conformity_and_blocks_lot(
    measurement_setup,
) -> None:
    tenant, user, critical_point, lot = measurement_setup
    with use_tenant(tenant.id):
        measurement = record_measurement(
            critical_point,
            tenant=tenant,
            value=Decimal(95),
            measured_by=user,
            lot_variant_id=lot.variant_id,
            lot_name=lot.name,
        )
        assert measurement.is_within_limits is False

        non_conformities = QltNonConformity.objects.filter(tenant=tenant)
        assert non_conformities.count() == 1
        non_conformity = non_conformities.first()
        assert non_conformity is not None
        assert non_conformity.state == QltNonConformity.STATE_OPEN
        assert non_conformity.measurement_id == measurement.id
        assert non_conformity.opened_by_id == user.id
        assert non_conformity.description  # motif renseigne automatiquement

        lot.refresh_from_db()
        assert lot.is_held() is True


def test_record_measurement_below_min_also_blocks(measurement_setup) -> None:
    tenant, user, critical_point, lot = measurement_setup
    with use_tenant(tenant.id):
        record_measurement(
            critical_point,
            tenant=tenant,
            value=Decimal(10),
            measured_by=user,
            lot_variant_id=lot.variant_id,
            lot_name=lot.name,
        )
        lot.refresh_from_db()
        assert lot.is_held() is True


def test_record_measurement_without_lot_identity_still_opens_non_conformity(
    measurement_setup,
) -> None:
    """Aucun `lot_variant_id`/`lot_name` fourni : la non-conformité reste
    ouverte (le signal de conformité n'est jamais perdu) mais aucun
    blocage de lot n'est tenté — pas de crash, pas d'appel `stocks`."""
    tenant, user, critical_point, _lot = measurement_setup
    with use_tenant(tenant.id):
        measurement = record_measurement(
            critical_point, tenant=tenant, value=Decimal(99), measured_by=user
        )
        assert measurement.is_within_limits is False
        assert QltNonConformity.objects.filter(tenant=tenant).count() == 1


def test_release_lot_hold_refused_while_non_conformity_open(measurement_setup) -> None:
    tenant, user, critical_point, lot = measurement_setup
    with use_tenant(tenant.id):
        record_measurement(
            critical_point,
            tenant=tenant,
            value=Decimal(95),
            measured_by=user,
            lot_variant_id=lot.variant_id,
            lot_name=lot.name,
        )
        with pytest.raises(ValidationError):
            release_lot_hold(
                tenant=tenant,
                lot_variant_id=lot.variant_id,
                lot_name=lot.name,
                released_by=user,
                reason="Vérification effectuée",
            )
        lot.refresh_from_db()
        assert lot.is_held() is True


def test_release_lot_hold_succeeds_after_non_conformity_closed(measurement_setup) -> None:
    tenant, user, critical_point, lot = measurement_setup
    with use_tenant(tenant.id):
        record_measurement(
            critical_point,
            tenant=tenant,
            value=Decimal(95),
            measured_by=user,
            lot_variant_id=lot.variant_id,
            lot_name=lot.name,
        )
        non_conformity = QltNonConformity.objects.get(tenant=tenant)
        close_non_conformity(non_conformity, closed_by=user, closing_reason="Analyse refaite, OK")

        quality_state_id = release_lot_hold(
            tenant=tenant,
            lot_variant_id=lot.variant_id,
            lot_name=lot.name,
            released_by=user,
            reason="Analyse refaite, OK",
        )
        assert quality_state_id is not None

        lot = StkLot.objects.get(id=lot.id)
        assert lot.is_held() is False


def test_release_lot_hold_requires_reason(measurement_setup) -> None:
    tenant, user, _critical_point, lot = measurement_setup
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        release_lot_hold(
            tenant=tenant,
            lot_variant_id=lot.variant_id,
            lot_name=lot.name,
            released_by=user,
            reason="",
        )
