"""INT3 (chantier interactivite native inter-modules) : `flag_customs_file_
risk` transforme un dossier douanier reellement a risque (ouvert depuis
plus de `OPEN_TOO_LONG_DAYS`, meme seuil que l'anomalie deterministe
`logistics.customs_file_at_risk`, INT2) en `RiskItem` generique reel."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.core.models.risk import CATEGORY_LOGISTICS, RiskItem
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.logistics.services.ai_anomaly_registration import OPEN_TOO_LONG_DAYS
from apps.logistics.services.customs import (
    create_customs_file,
    create_hs_code,
    flag_customs_file_risk,
    mark_customs_file_cleared,
)
from apps.logistics.services.shipments import create_shipment

pytestmark = pytest.mark.django_db


@pytest.fixture
def customs_risk_setup():
    tenant = Tenant.objects.create(code="LOG-INT3", name="Logistics INT3 Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="log-int3@example.com", password="Str0ngPassw0rd!23")
        shipment = create_shipment(tenant, origin="Guangzhou", destination="Toamasina")
        create_hs_code(
            tenant, code="6109.1000", description="T-shirts en coton", duty_rate_pct=Decimal("20")
        )
        return tenant, user, shipment


def test_flag_customs_file_risk_creates_risk_item_when_open_too_long(customs_risk_setup) -> None:
    tenant, user, shipment = customs_risk_setup
    with use_tenant(tenant.id):
        cutoff = dt.date.today() - dt.timedelta(days=OPEN_TOO_LONG_DAYS + 1)
        customs_file = create_customs_file(tenant, shipment=shipment, opened_at=cutoff)

        risk_item = flag_customs_file_risk(customs_file, owner=user)

        assert risk_item is not None
        assert risk_item.category == CATEGORY_LOGISTICS
        assert risk_item.content_object == customs_file
        assert risk_item.owner_id == user.id
        assert RiskItem.objects.filter(tenant=tenant).count() == 1


def test_flag_customs_file_risk_returns_none_when_recently_opened(customs_risk_setup) -> None:
    """Cas normal (dossier ouvert recemment, pas encore a risque) : AUCUN
    `RiskItem` ne doit etre cree."""
    tenant, user, shipment = customs_risk_setup
    with use_tenant(tenant.id):
        customs_file = create_customs_file(tenant, shipment=shipment, opened_at=dt.date.today())

        risk_item = flag_customs_file_risk(customs_file, owner=user)

        assert risk_item is None
        assert RiskItem.objects.filter(tenant=tenant).count() == 0


def test_flag_customs_file_risk_returns_none_once_cleared(customs_risk_setup) -> None:
    """Cas normal (dossier deja dedouane, meme s'il est vieux) : AUCUN
    `RiskItem` ne doit etre cree."""
    tenant, user, shipment = customs_risk_setup
    with use_tenant(tenant.id):
        cutoff = dt.date.today() - dt.timedelta(days=OPEN_TOO_LONG_DAYS + 1)
        customs_file = create_customs_file(tenant, shipment=shipment, opened_at=cutoff)
        mark_customs_file_cleared(customs_file)

        risk_item = flag_customs_file_risk(customs_file, owner=user)

        assert risk_item is None
        assert RiskItem.objects.filter(tenant=tenant).count() == 0
