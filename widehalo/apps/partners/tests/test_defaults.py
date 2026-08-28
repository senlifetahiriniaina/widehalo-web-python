from __future__ import annotations

import pytest

from apps.core.models.tenant import Tenant
from apps.core.services.entity_resolution import ResolutionConfidence
from apps.core.tests.utils import use_tenant
from apps.partners.models import Partner
from apps.partners.services.defaults import ensure_default_partner
from apps.partners.services.onboarding import create_partner
from apps.partners.services.public import find_partner_by_name

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return Tenant.objects.create(code="PART-QUALIF-T", name="Partners Qualif Tenant")


def test_ensure_default_partner_creates_a_placeholder(tenant) -> None:
    with use_tenant(tenant.id):
        placeholder = ensure_default_partner(tenant, Partner.ROLE_SUPPLIER)

    assert placeholder.is_placeholder is True
    assert placeholder.roles == [Partner.ROLE_SUPPLIER]


def test_ensure_default_partner_is_idempotent_per_role(tenant) -> None:
    with use_tenant(tenant.id):
        first = ensure_default_partner(tenant, Partner.ROLE_SUPPLIER)
        second = ensure_default_partner(tenant, Partner.ROLE_SUPPLIER)
        placeholder_count = Partner.objects.filter(tenant=tenant, is_placeholder=True).count()

    assert first.id == second.id
    assert placeholder_count == 1


def test_ensure_default_partner_creates_one_placeholder_per_role(tenant) -> None:
    with use_tenant(tenant.id):
        supplier_placeholder = ensure_default_partner(tenant, Partner.ROLE_SUPPLIER)
        client_placeholder = ensure_default_partner(tenant, Partner.ROLE_CLIENT)

    assert supplier_placeholder.id != client_placeholder.id


def test_find_partner_by_name_exact_match(tenant) -> None:
    with use_tenant(tenant.id):
        create_partner(
            tenant=tenant, name="Établissement Éléphant Bleu", roles=[Partner.ROLE_CLIENT]
        )

        result = find_partner_by_name(tenant, "etablissement elephant bleu")

    assert result.confidence == ResolutionConfidence.EXACT
    assert result.entity_id is not None


def test_find_partner_by_name_unresolved_when_no_match(tenant) -> None:
    with use_tenant(tenant.id):
        result = find_partner_by_name(tenant, "Inconnu Sarl")

    assert result.confidence == ResolutionConfidence.UNRESOLVED
    assert result.entity_id is None


def test_find_partner_by_name_unresolved_when_ambiguous(tenant) -> None:
    with use_tenant(tenant.id):
        create_partner(tenant=tenant, name="Textiles Sarl", roles=[Partner.ROLE_CLIENT])
        create_partner(tenant=tenant, name="TEXTILES SARL", roles=[Partner.ROLE_SUPPLIER])

        result = find_partner_by_name(tenant, "Textiles Sarl")

    assert result.confidence == ResolutionConfidence.UNRESOLVED
    assert result.entity_id is None


def test_find_partner_by_name_ignores_placeholders(tenant) -> None:
    with use_tenant(tenant.id):
        ensure_default_partner(tenant, Partner.ROLE_SUPPLIER)

        result = find_partner_by_name(tenant, "Fournisseur à qualifier")

    assert result.confidence == ResolutionConfidence.UNRESOLVED


def test_find_partner_by_name_blank_name_is_unresolved(tenant) -> None:
    with use_tenant(tenant.id):
        result = find_partner_by_name(tenant, "   ")

    assert result.confidence == ResolutionConfidence.UNRESOLVED
