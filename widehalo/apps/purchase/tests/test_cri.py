"""Tests PU7 (§5.6.2, cf. plan) : `PurCri` (compte rendu d'incident
achats), creation et cloture."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.purchase.models import PurCri
from apps.purchase.services.cri import close_cri, create_cri

pytestmark = pytest.mark.django_db


@pytest.fixture
def cri_setup():
    tenant = Tenant.objects.create(code="PUR-CRI", name="Purchase CRI Tenant")
    with use_tenant(tenant.id):
        return tenant


def test_create_cri_generates_sequenced_reference_in_draft(cri_setup) -> None:
    tenant = cri_setup
    with use_tenant(tenant.id):
        cri = create_cri(
            tenant=tenant,
            date=dt.date.today(),
            type=PurCri.TYPE_RETARD,
            partner_id=uuid.uuid4(),
            description="Livraison retardee de 10 jours",
        )
        assert cri.reference.startswith("PCRI-")
        assert cri.state == PurCri.STATE_DRAFT
        assert cri.cost_mga == Decimal(0)
        assert cri.attachment_document_ids == []


def test_create_cri_stores_attachment_document_ids(cri_setup) -> None:
    tenant = cri_setup
    with use_tenant(tenant.id):
        doc_id = uuid.uuid4()
        cri = create_cri(
            tenant=tenant,
            date=dt.date.today(),
            type=PurCri.TYPE_NON_CONFORMITE,
            partner_id=uuid.uuid4(),
            description="Matiere non conforme",
            attachment_document_ids=[doc_id],
        )
        assert cri.attachment_document_ids == [str(doc_id)]


def test_close_cri_moves_draft_to_closed_and_updates_action_taken(cri_setup) -> None:
    tenant = cri_setup
    with use_tenant(tenant.id):
        cri = create_cri(
            tenant=tenant,
            date=dt.date.today(),
            type=PurCri.TYPE_RUPTURE,
            partner_id=uuid.uuid4(),
            description="Rupture de stock fournisseur",
        )
        close_cri(cri, action_taken="Fournisseur de secours active")
        cri.refresh_from_db()
        assert cri.state == PurCri.STATE_CLOSED
        assert cri.action_taken == "Fournisseur de secours active"


def test_close_cri_without_new_action_taken_keeps_existing_value(cri_setup) -> None:
    tenant = cri_setup
    with use_tenant(tenant.id):
        cri = create_cri(
            tenant=tenant,
            date=dt.date.today(),
            type=PurCri.TYPE_INCIDENT_DOUANE,
            partner_id=uuid.uuid4(),
            description="Blocage douanier",
            action_taken="Dossier transmis au transitaire",
        )
        close_cri(cri)
        cri.refresh_from_db()
        assert cri.state == PurCri.STATE_CLOSED
        assert cri.action_taken == "Dossier transmis au transitaire"


def test_close_cri_refuses_double_close(cri_setup) -> None:
    tenant = cri_setup
    with use_tenant(tenant.id):
        cri = create_cri(
            tenant=tenant,
            date=dt.date.today(),
            type=PurCri.TYPE_LITIGE,
            partner_id=uuid.uuid4(),
            description="Litige facture",
        )
        close_cri(cri)
        with pytest.raises(ValidationError):
            close_cri(cri)
