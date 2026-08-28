"""Tests du contrat public de `purchase` (`apps/purchase/services/public.py`)
— seule surface que les autres apps metier ont le droit d'importer. Couvre
`open_purchase_incident`, gap ajoute pour ST3 de `stocks` (RG-STK-4, cf.
plan), et `create_requisition_line_from_source`, gap ajoute par le
chantier de durcissement retroactif qui leve le stub RG-SAL-3 "a acheter"
de `sales.services.procurement`."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.catalog.models import ProductTemplate, ProductVariant, UnitOfMeasure
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.purchase.models import PurCri, PurRequisition, PurRequisitionLine
from apps.purchase.services.public import (
    create_requisition_line_from_source,
    open_purchase_incident,
)

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


# ---------------------------------------------------------------------------
# create_requisition_line_from_source — chantier de durcissement retroactif
# (leve le stub RG-SAL-3 "a acheter" de `sales.services.procurement`).
# ---------------------------------------------------------------------------


@pytest.fixture
def requisition_source_setup():
    tenant = Tenant.objects.create(code="PUR-PUB-REQ", name="Purchase Public Requisition Tenant")
    with use_tenant(tenant.id):
        requester = User.objects.create_user(
            email="pur-pub-req@example.com", password="Str0ngPassw0rd!23"
        )
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PC-REQ", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )
        template = ProductTemplate.objects.create(
            tenant=tenant,
            name="Bouton",
            base_uom=uom,
            reference="TPL-PUR-PUB-REQ",
            base_price_mga=Decimal("500"),
        )
        variant = ProductVariant.objects.create(
            tenant=tenant, template=template, reference="VAR-PUR-PUB-REQ"
        )
        return tenant, requester, variant


def test_create_requisition_line_from_source_creates_a_real_draft_requisition(
    requisition_source_setup,
) -> None:
    tenant, requester, variant = requisition_source_setup
    with use_tenant(tenant.id):
        line_id = create_requisition_line_from_source(
            tenant,
            requester_user_id=requester.id,
            variant_id=variant.id,
            qty=Decimal(20),
            date_needed=dt.date(2026, 3, 1),
            description="Reapprovisionnement declenche par une commande de vente",
        )

        assert line_id is not None
        line = PurRequisitionLine.objects.get(id=line_id)
        assert line.variant_id == variant.id
        assert line.qty == Decimal(20)
        assert line.requisition.requester_id == requester.id
        assert line.requisition.state == PurRequisition.STATE_DRAFT
        assert line.requisition.date_needed == dt.date(2026, 3, 1)


def test_create_requisition_line_from_source_returns_none_without_valid_requester(
    requisition_source_setup,
) -> None:
    tenant, _requester, variant = requisition_source_setup
    with use_tenant(tenant.id):
        line_id = create_requisition_line_from_source(
            tenant,
            requester_user_id=uuid.uuid4(),
            variant_id=variant.id,
            qty=Decimal(5),
            date_needed=dt.date(2026, 3, 1),
        )

        assert line_id is None
        assert not PurRequisition.objects.exists()


def test_create_requisition_line_from_source_returns_none_without_real_variant(
    requisition_source_setup,
) -> None:
    tenant, requester, _variant = requisition_source_setup
    with use_tenant(tenant.id):
        line_id = create_requisition_line_from_source(
            tenant,
            requester_user_id=requester.id,
            variant_id=uuid.uuid4(),
            qty=Decimal(5),
            date_needed=dt.date(2026, 3, 1),
        )

        assert line_id is None
        # La demande cree puis avortee (echec de resolution de variante)
        # est annulee en transaction — aucune demande orpheline sans ligne.
        assert not PurRequisition.objects.exists()
