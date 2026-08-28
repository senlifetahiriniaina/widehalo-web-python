"""Tests PU7 (§5.6.2, cf. plan) : `PurCra` (compte rendu d'activite
achats), workflow `draft -> submitted -> validated/rejected`."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.purchase.models import PurCra
from apps.purchase.services.cra import create_cra, reject_cra, submit_cra, validate_cra

pytestmark = pytest.mark.django_db


@pytest.fixture
def cra_setup():
    tenant = Tenant.objects.create(code="PUR-CRA", name="Purchase CRA Tenant")
    with use_tenant(tenant.id):
        buyer = User.objects.create_user(
            email="acheteur-cra@example.com", password="Str0ngPassw0rd!23"
        )
        return tenant, buyer


def test_create_cra_generates_sequenced_reference_in_draft(cra_setup) -> None:
    tenant, buyer = cra_setup
    with use_tenant(tenant.id):
        cra = create_cra(
            tenant=tenant,
            date=dt.date.today(),
            buyer=buyer,
            partner_id=uuid.uuid4(),
            activity_type=PurCra.TYPE_SOURCING,
            hours=Decimal("3.5"),
        )
        assert cra.reference.startswith("PCRA-")
        assert cra.state == PurCra.STATE_DRAFT
        assert cra.hours == Decimal("3.5")


def test_submit_cra_moves_draft_to_submitted(cra_setup) -> None:
    tenant, buyer = cra_setup
    with use_tenant(tenant.id):
        cra = create_cra(
            tenant=tenant,
            date=dt.date.today(),
            buyer=buyer,
            partner_id=uuid.uuid4(),
            activity_type=PurCra.TYPE_NEGOCIATION,
            hours=Decimal("2"),
        )
        submit_cra(cra)
        cra.refresh_from_db()
        assert cra.state == PurCra.STATE_SUBMITTED


def test_submit_cra_refuses_when_not_draft(cra_setup) -> None:
    tenant, buyer = cra_setup
    with use_tenant(tenant.id):
        cra = create_cra(
            tenant=tenant,
            date=dt.date.today(),
            buyer=buyer,
            partner_id=uuid.uuid4(),
            activity_type=PurCra.TYPE_RELANCE,
            hours=Decimal("1"),
        )
        submit_cra(cra)
        with pytest.raises(ValidationError):
            submit_cra(cra)


def test_validate_cra_moves_submitted_to_validated(cra_setup) -> None:
    tenant, buyer = cra_setup
    with use_tenant(tenant.id):
        cra = create_cra(
            tenant=tenant,
            date=dt.date.today(),
            buyer=buyer,
            partner_id=uuid.uuid4(),
            activity_type=PurCra.TYPE_VISITE,
            hours=Decimal("4"),
        )
        submit_cra(cra)
        validate_cra(cra, validated_by=buyer)
        cra.refresh_from_db()
        assert cra.state == PurCra.STATE_VALIDATED


def test_validate_cra_refuses_when_not_submitted(cra_setup) -> None:
    tenant, buyer = cra_setup
    with use_tenant(tenant.id):
        cra = create_cra(
            tenant=tenant,
            date=dt.date.today(),
            buyer=buyer,
            partner_id=uuid.uuid4(),
            activity_type=PurCra.TYPE_AUDIT,
            hours=Decimal("6"),
        )
        with pytest.raises(ValidationError):
            validate_cra(cra)


def test_reject_cra_requires_non_empty_reason(cra_setup) -> None:
    tenant, buyer = cra_setup
    with use_tenant(tenant.id):
        cra = create_cra(
            tenant=tenant,
            date=dt.date.today(),
            buyer=buyer,
            partner_id=uuid.uuid4(),
            activity_type=PurCra.TYPE_SOURCING,
            hours=Decimal("2"),
        )
        submit_cra(cra)
        with pytest.raises(ValidationError):
            reject_cra(cra, reason="")


def test_reject_cra_moves_submitted_to_rejected(cra_setup) -> None:
    tenant, buyer = cra_setup
    with use_tenant(tenant.id):
        cra = create_cra(
            tenant=tenant,
            date=dt.date.today(),
            buyer=buyer,
            partner_id=uuid.uuid4(),
            activity_type=PurCra.TYPE_SOURCING,
            hours=Decimal("2"),
        )
        submit_cra(cra)
        reject_cra(cra, reason="Heures non justifiees")
        cra.refresh_from_db()
        assert cra.state == PurCra.STATE_REJECTED
        assert cra.rejection_reason == "Heures non justifiees"


def test_reject_cra_refuses_when_not_submitted(cra_setup) -> None:
    tenant, buyer = cra_setup
    with use_tenant(tenant.id):
        cra = create_cra(
            tenant=tenant,
            date=dt.date.today(),
            buyer=buyer,
            partner_id=uuid.uuid4(),
            activity_type=PurCra.TYPE_SOURCING,
            hours=Decimal("2"),
        )
        with pytest.raises(ValidationError):
            reject_cra(cra, reason="Motif")
