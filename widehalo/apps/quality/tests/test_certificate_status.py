"""Bloc D, D2 (QUA-8) : `get_lot_certificate_status` — lecture pure,
jamais bloquante, déléguant à `stocks.services.public.
get_lot_certificate_document_id`. Le blocage réel à la réception est testé
dans `apps.stocks.tests.test_public`."""

from __future__ import annotations

import uuid

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.quality.services.public import get_lot_certificate_status
from apps.stocks.tests.factories import StkLotFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def certificate_status_setup():
    tenant = Tenant.objects.create(code="QLT-COA", name="Quality Certificate Tenant")
    with use_tenant(tenant.id):
        lot_with_certificate = StkLotFactory(
            tenant=tenant, name="LOT-COA-001", certificate_document_id=uuid.uuid4()
        )
        lot_without_certificate = StkLotFactory(
            tenant=tenant, name="LOT-COA-002", certificate_document_id=None
        )
        return tenant, lot_with_certificate, lot_without_certificate


def test_get_lot_certificate_status_true_when_certificate_attached(
    certificate_status_setup,
) -> None:
    tenant, lot_with_certificate, _lot_without_certificate = certificate_status_setup
    with use_tenant(tenant.id):
        assert (
            get_lot_certificate_status(
                tenant=tenant,
                lot_variant_id=lot_with_certificate.variant_id,
                lot_name=lot_with_certificate.name,
            )
            is True
        )


def test_get_lot_certificate_status_false_when_lot_has_no_certificate(
    certificate_status_setup,
) -> None:
    tenant, _lot_with_certificate, lot_without_certificate = certificate_status_setup
    with use_tenant(tenant.id):
        assert (
            get_lot_certificate_status(
                tenant=tenant,
                lot_variant_id=lot_without_certificate.variant_id,
                lot_name=lot_without_certificate.name,
            )
            is False
        )


def test_get_lot_certificate_status_false_when_lot_unknown(certificate_status_setup) -> None:
    tenant, _lot_with_certificate, _lot_without_certificate = certificate_status_setup
    with use_tenant(tenant.id):
        assert (
            get_lot_certificate_status(tenant=tenant, lot_variant_id=uuid.uuid4(), lot_name="")
            is False
        )
