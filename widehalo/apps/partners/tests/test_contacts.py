from __future__ import annotations

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.partners.models import Partner
from apps.partners.services.contacts import create_contact, list_contacts, update_contact
from apps.partners.services.onboarding import create_partner
from apps.partners.services.public import (
    ROLE_ASSOCIATE,
    ROLE_BANK,
    ROLE_COLLABORATOR,
    list_role_choices,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return Tenant.objects.create(code="PART-CT", name="Partners Contacts Tenant")


def test_new_roles_are_present_in_role_choices() -> None:
    codes = {code for code, _label in Partner.ROLE_CHOICES}
    assert {"associate", "collaborator", "bank"} <= codes
    assert ROLE_ASSOCIATE == "associate"
    assert ROLE_COLLABORATOR == "collaborator"
    assert ROLE_BANK == "bank"


def test_list_role_choices_mirrors_partner_role_choices() -> None:
    assert list_role_choices() == list(Partner.ROLE_CHOICES)


def test_create_contact_general_appears_on_every_tab(tenant) -> None:
    with use_tenant(tenant.id):
        partner = create_partner(
            tenant=tenant, name="Textiles Sarl", roles=[Partner.ROLE_CLIENT, Partner.ROLE_SUPPLIER]
        )
        create_contact(partner=partner, full_name="Rina R.", email="rina@example.com")

        assert [c.full_name for c in list_contacts(partner, role=Partner.ROLE_CLIENT)] == [
            "Rina R."
        ]
        assert [c.full_name for c in list_contacts(partner, role=Partner.ROLE_SUPPLIER)] == [
            "Rina R."
        ]


def test_create_contact_scoped_to_a_role_is_hidden_on_other_tabs(tenant) -> None:
    with use_tenant(tenant.id):
        partner = create_partner(
            tenant=tenant, name="Textiles Sarl", roles=[Partner.ROLE_CLIENT, Partner.ROLE_SUPPLIER]
        )
        create_contact(
            partner=partner, full_name="Achats Only", role=Partner.ROLE_SUPPLIER, email="a@x.com"
        )

        assert list_contacts(partner, role=Partner.ROLE_SUPPLIER)
        assert list_contacts(partner, role=Partner.ROLE_CLIENT) == []


def test_list_contacts_without_role_returns_all(tenant) -> None:
    with use_tenant(tenant.id):
        partner = create_partner(tenant=tenant, name="Textiles Sarl", roles=[Partner.ROLE_CLIENT])
        create_contact(partner=partner, full_name="General", email="g@x.com")
        create_contact(
            partner=partner, full_name="Client Only", role=Partner.ROLE_CLIENT, email="c@x.com"
        )

        names = {c.full_name for c in list_contacts(partner)}
        assert names == {"General", "Client Only"}


def test_update_contact_persists_changes(tenant) -> None:
    with use_tenant(tenant.id):
        partner = create_partner(tenant=tenant, name="Textiles Sarl", roles=[Partner.ROLE_CLIENT])
        contact = create_contact(partner=partner, full_name="Old Name", email="old@x.com")

        update_contact(contact, full_name="New Name", email="new@x.com", is_primary=True)
        contact.refresh_from_db()

        assert contact.full_name == "New Name"
        assert contact.email == "new@x.com"
        assert contact.is_primary is True
