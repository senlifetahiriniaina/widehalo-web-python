from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.services.workflow import TransitionPermissionError
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import grant_role, use_tenant
from apps.financing.models import FinCredoc
from apps.financing.services.credoc import (
    close_credoc,
    create_credoc,
    open_credoc,
    pay_credoc,
    receive_documents,
)

pytestmark = pytest.mark.django_db


def _credoc(tenant: Tenant) -> FinCredoc:
    return create_credoc(
        tenant,
        purchase_order_id=uuid.uuid4(),
        bank="Banque emettrice",
        beneficiary="Fournisseur import",
        amount_mga=Decimal("30000000"),
        validity_date=dt.date(2026, 12, 31),
    )


def test_create_credoc_generates_reference_and_defaults_to_requested_state() -> None:
    tenant = Tenant.objects.create(code="FIN-CRED1", name="Financing Credoc Tenant 1")
    with use_tenant(tenant.id):
        credoc = _credoc(tenant)
        assert credoc.reference.startswith("FINCREDOC-")
        assert credoc.state == FinCredoc.STATE_REQUESTED


def test_create_credoc_rejects_non_positive_amount() -> None:
    tenant = Tenant.objects.create(code="FIN-CRED2", name="Financing Credoc Tenant 2")
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        create_credoc(
            tenant,
            purchase_order_id=uuid.uuid4(),
            bank="Banque emettrice",
            beneficiary="Fournisseur",
            amount_mga=Decimal("0"),
            validity_date=dt.date(2026, 12, 31),
        )


def test_credoc_full_workflow() -> None:
    tenant = Tenant.objects.create(code="FIN-CRED3", name="Financing Credoc Tenant 3")
    with use_tenant(tenant.id):
        user = UserFactory()
        grant_role(user, "comptable")
        credoc = _credoc(tenant)

        open_credoc(credoc, user, reason="Accord de la banque émettrice reçu")
        credoc.refresh_from_db()
        assert credoc.state == FinCredoc.STATE_OPENED

        receive_documents(credoc, user, reason="Jeu de documents complet reçu du fournisseur")
        credoc.refresh_from_db()
        assert credoc.state == FinCredoc.STATE_DOCUMENTS_RECEIVED

        pay_credoc(credoc, user, reason="Documents conformes, paiement autorisé")
        credoc.refresh_from_db()
        assert credoc.state == FinCredoc.STATE_PAID

        close_credoc(credoc, user, reason="Marchandise livrée, dossier soldé")
        credoc.refresh_from_db()
        assert credoc.state == FinCredoc.STATE_CLOSED


def test_credoc_cannot_skip_states() -> None:
    tenant = Tenant.objects.create(code="FIN-CRED4", name="Financing Credoc Tenant 4")
    with use_tenant(tenant.id):
        user = UserFactory()
        grant_role(user, "comptable")
        credoc = _credoc(tenant)

        with pytest.raises(TransitionPermissionError):
            pay_credoc(credoc, user, reason="Tentative de saut d'étape")


# B2 (Phase 3, "transitions motivées") : motif obligatoire sur les 4
# transitions — même patron que
# `apps.logistics.tests.test_shipments::test_block_shipment_requires_reason`.
def test_credoc_transitions_require_a_reason() -> None:
    tenant = Tenant.objects.create(code="FIN-CRED5", name="Financing Credoc Tenant 5")
    with use_tenant(tenant.id):
        user = UserFactory()
        grant_role(user, "comptable")
        credoc = _credoc(tenant)

        with pytest.raises(ValidationError):
            open_credoc(credoc, user, reason="")
        credoc.refresh_from_db()
        assert credoc.state == FinCredoc.STATE_REQUESTED

        open_credoc(credoc, user, reason="Accord de la banque émettrice reçu")
        with pytest.raises(ValidationError):
            receive_documents(credoc, user, reason="")
