"""Tests du contrat public de `partners` (`apps/partners/services/
public.py`) — seule surface que les autres apps metier ont le droit
d'importer. Couvre le gap ajoute pour le module `pos` (§13.5) :
`search_partners`."""

from __future__ import annotations

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.partners.services.public import search_partners
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
