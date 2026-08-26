from __future__ import annotations

from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.partners.models import DuplicateAlert, Partner
from apps.partners.services.merge import merge_partners
from apps.partners.services.onboarding import create_partner
from apps.partners.services.public import is_over_credit_limit, partner_has_role

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return Tenant.objects.create(code="PART-T", name="Partners Tenant")


def test_create_partner_assigns_a_sequenced_reference(tenant) -> None:
    with use_tenant(tenant.id):
        partner = create_partner(tenant=tenant, name="Textiles Sarl", roles=[Partner.ROLE_CLIENT])
        assert partner.reference.startswith("PART-")


def test_duplicate_nif_raises_an_alert_but_does_not_block_creation(tenant) -> None:
    with use_tenant(tenant.id):
        first = create_partner(
            tenant=tenant, name="Alpha", roles=[Partner.ROLE_SUPPLIER], nif="NIF-001"
        )
        second = create_partner(
            tenant=tenant, name="Alpha Bis", roles=[Partner.ROLE_SUPPLIER], nif="NIF-001"
        )

        assert Partner.objects.filter(nif="NIF-001").count() == 2
        alert = DuplicateAlert.objects.get(partner=second)
        assert alert.duplicate_of_id == first.id


def test_partner_without_credit_limit_is_never_over_limit(tenant) -> None:
    with use_tenant(tenant.id):
        partner = create_partner(tenant=tenant, name="Beta", roles=[Partner.ROLE_CLIENT])
        assert not is_over_credit_limit(partner.id, Decimal("999999"))


def test_partner_over_credit_limit_is_detected(tenant) -> None:
    with use_tenant(tenant.id):
        partner = create_partner(
            tenant=tenant, name="Gamma", roles=[Partner.ROLE_CLIENT], credit_limit_mga=100000
        )
        assert is_over_credit_limit(partner.id, Decimal("150000"))
        assert not is_over_credit_limit(partner.id, Decimal("50000"))


def test_partner_has_role(tenant) -> None:
    with use_tenant(tenant.id):
        partner = create_partner(
            tenant=tenant, name="Delta", roles=[Partner.ROLE_CLIENT, Partner.ROLE_SUPPLIER]
        )
        assert partner_has_role(partner.id, Partner.ROLE_CLIENT)
        assert not partner_has_role(partner.id, Partner.ROLE_CARRIER)


def test_merge_reassigns_related_records_and_preserves_audit(tenant) -> None:
    from apps.core.models.audit import AuditLog

    with use_tenant(tenant.id):
        primary = create_partner(tenant=tenant, name="Primary", roles=[Partner.ROLE_CLIENT])
        duplicate = create_partner(tenant=tenant, name="Duplicate", roles=[Partner.ROLE_CLIENT])

        alert = DuplicateAlert.objects.create(
            tenant=tenant, partner=duplicate, duplicate_of=primary
        )

        reassigned = merge_partners(primary=primary, duplicate=duplicate)

        assert reassigned >= 1
        alert.refresh_from_db()
        assert alert.partner_id == primary.id

        duplicate.refresh_from_db()
        assert duplicate.merged_into_id == primary.id
        assert duplicate.is_active is False

        # L'audit transversal (etape 10) a bien trace la modification du
        # DuplicateAlert reassigne et le soft-delete du doublon.
        assert AuditLog.objects.filter(
            content_type__model="duplicatealert", object_id=str(alert.id)
        ).exists()
        assert AuditLog.objects.filter(
            content_type__model="partner", object_id=str(duplicate.id)
        ).exists()
