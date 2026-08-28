"""Tests du contrat public de `purchase` (`apps/purchase/services/public.py`)
— seule surface que les autres apps metier ont le droit d'importer. Couvre
`open_purchase_incident`, gap ajoute pour ST3 de `stocks` (RG-STK-4, cf.
plan)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.purchase.models import PurCri
from apps.purchase.services.public import open_purchase_incident

pytestmark = pytest.mark.django_db


@pytest.fixture
def incident_setup():
    tenant = Tenant.objects.create(code="PUR-PUB-INC", name="Purchase Public Incident Tenant")
    with use_tenant(tenant.id):
        return tenant


def test_open_purchase_incident_creates_a_real_pur_cri(incident_setup) -> None:
    tenant = incident_setup
    partner_id = uuid.uuid4()
    with use_tenant(tenant.id):
        incident_id = open_purchase_incident(
            tenant=tenant,
            type=PurCri.TYPE_NON_CONFORMITE,
            partner_id=partner_id,
            description="Ecart de mesure au-dela du seuil",
            cost_mga=Decimal("15000"),
        )

        cri = PurCri.objects.get(id=incident_id)
        assert cri.type == PurCri.TYPE_NON_CONFORMITE
        assert cri.partner_id == partner_id
        assert cri.description == "Ecart de mesure au-dela du seuil"
        assert cri.cost_mga == Decimal("15000")
        assert cri.state == PurCri.STATE_DRAFT
        assert cri.reference.startswith("PCRI-")
        assert cri.order is None


def test_open_purchase_incident_defaults(incident_setup) -> None:
    tenant = incident_setup
    with use_tenant(tenant.id):
        incident_id = open_purchase_incident(
            tenant=tenant,
            type=PurCri.TYPE_RUPTURE,
            partner_id=uuid.uuid4(),
            description="Rupture signalee",
        )
        cri = PurCri.objects.get(id=incident_id)
        assert cri.impact == ""
        assert cri.cost_mga == Decimal(0)
        assert cri.attachment_document_ids == []
