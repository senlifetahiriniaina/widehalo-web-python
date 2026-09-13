"""Tests du contrat public de `partners` (`apps/partners/services/
public.py`) — seule surface que les autres apps metier ont le droit
d'importer. Couvre le gap ajoute pour le module `pos` (§13.5) :
`search_partners`."""

from __future__ import annotations

import uuid

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.partners.models import PartnerContact
from apps.partners.services.public import get_partner_phone, search_partners
from apps.partners.tests.factories import PartnerFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    t = Tenant.objects.create(code="PTN-PUB", name="Partners Public Tenant")
    with use_tenant(t.id):
        yield t


def test_search_partners_matches_name_or_nif_case_insensitively(tenant) -> None:
    match = PartnerFactory(tenant=tenant, name="Établissements Rakoto", nif="1234567")
    PartnerFactory(tenant=tenant, name="Autre société", nif="9999999")

    by_name = search_partners(tenant, "rakoto")
    by_nif = search_partners(tenant, "123456")

    assert [row["id"] for row in by_name] == [str(match.id)]
    assert [row["id"] for row in by_nif] == [str(match.id)]


def test_search_partners_returns_an_empty_list_for_an_empty_query(tenant) -> None:
    PartnerFactory(tenant=tenant)

    assert search_partners(tenant, "") == []
    assert search_partners(tenant, "   ") == []


def test_search_partners_excludes_placeholders(tenant) -> None:
    PartnerFactory(tenant=tenant, name="Client fantôme RG-QUALIF", is_placeholder=True)

    assert search_partners(tenant, "fantôme") == []


def test_get_partner_phone_prefers_the_primary_contact(tenant) -> None:
    """SAL-NOTIF1 — le lien WhatsApp d'un devis lit ce numero. `Partner`
    n'a aucun champ telephone : sans ce gap, `sales` n'avait rien a
    composer, et `build_whatsapp_link` restait sans appelant depuis S7."""
    partner = PartnerFactory(tenant=tenant)
    PartnerContact.objects.create(
        tenant=tenant, partner=partner, full_name="Secondaire", phone="+261 32 00 000 00"
    )
    PartnerContact.objects.create(
        tenant=tenant,
        partner=partner,
        full_name="Principal",
        phone="+261 34 12 345 67",
        is_primary=True,
    )

    assert get_partner_phone(partner.id) == "+261 34 12 345 67"


def test_get_partner_phone_falls_back_to_any_contact_with_a_number(tenant) -> None:
    """Un contact principal SANS numero ne doit pas masquer un contact
    secondaire qui en a un."""
    partner = PartnerFactory(tenant=tenant)
    PartnerContact.objects.create(
        tenant=tenant, partner=partner, full_name="Sans numero", is_primary=True
    )
    PartnerContact.objects.create(
        tenant=tenant, partner=partner, full_name="Avec numero", phone="+261 33 11 222 33"
    )

    assert get_partner_phone(partner.id) == "+261 33 11 222 33"


def test_get_partner_phone_is_empty_without_a_number_or_a_partner(tenant) -> None:
    partner = PartnerFactory(tenant=tenant)

    assert get_partner_phone(partner.id) == ""
    assert get_partner_phone(uuid.uuid4()) == ""
