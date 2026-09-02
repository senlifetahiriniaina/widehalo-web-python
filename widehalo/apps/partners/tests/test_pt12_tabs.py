"""Tests de l'ecran fiche partenaire a onglets par role et de la gestion
des contacts (chantier "fiche partenaire a onglets par role", PT12)."""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.partners.models import Partner, PartnerContact
from apps.partners.services.onboarding import create_partner

pytestmark = pytest.mark.django_db


def _login_with_tenant(tenant: Tenant, user: User) -> Client:
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def test_detail_screen_renders_a_tab_per_role_present() -> None:
    tenant = Tenant.objects.create(code="PT12-1", name="PT12 Tenant 1")
    user = User.objects.create_user(email="pt12-1@example.com", password="Str0ngPassw0rd!23")
    call_command("load_roles")
    # `commercial` : deja `partners: {view, add, change}` sans etre soumis
    # a MFA obligatoire (contrairement a `admin`/`comptable`) — evite de
    # devoir simuler un enrolement TOTP pour ce test de rendu.
    user.groups.add(Group.objects.get(name="commercial"))
    client = _login_with_tenant(tenant, user)

    with use_tenant(tenant.id):
        partner = create_partner(
            tenant=tenant,
            name="PT12 SARL",
            roles=[Partner.ROLE_CLIENT, Partner.ROLE_SUPPLIER, Partner.ROLE_BANK],
        )

    response = client.get(f"/partners/{partner.id}/")
    assert response.status_code == 200
    content = response.content.decode()
    soup = BeautifulSoup(content, "html.parser")
    tab_strip = soup.find(class_="tab-strip")
    assert tab_strip is not None
    tab_labels = [button.get_text(strip=True) for button in tab_strip.find_all("button")]
    assert "Général" in tab_labels
    assert "Client" in tab_labels
    assert "Fournisseur" in tab_labels
    assert "Banque" in tab_labels
    assert "Audit" in tab_labels
    # Roles absent du partenaire (transporteur/sous-traitant/associe/
    # collaborateur) ne recoivent jamais leur propre onglet — verifie sur les
    # boutons de la barre d'onglets uniquement (le formulaire d'ajout de
    # contact liste, lui, TOUS les roles possibles dans son <select>, ce qui
    # est correct et ne doit pas faire echouer cette assertion).
    assert "Transporteur" not in tab_labels


def test_detail_screen_shows_account_assignment_form_only_with_permission() -> None:
    tenant = Tenant.objects.create(code="PT12-2", name="PT12 Tenant 2")
    commercial = User.objects.create_user(
        email="pt12-commercial@example.com", password="Str0ngPassw0rd!23"
    )
    call_command("load_roles")
    commercial.groups.add(Group.objects.get(name="commercial"))
    client = _login_with_tenant(tenant, commercial)

    with use_tenant(tenant.id):
        partner = create_partner(tenant=tenant, name="PT12 SARL 2", roles=[Partner.ROLE_CLIENT])

    response = client.get(f"/partners/{partner.id}/")
    assert response.status_code == 200
    assert "Assigner un compte" not in response.content.decode()


def test_contact_create_edit_delete_lifecycle() -> None:
    tenant = Tenant.objects.create(code="PT12-3", name="PT12 Tenant 3")
    user = User.objects.create_user(email="pt12-3@example.com", password="Str0ngPassw0rd!23")
    call_command("load_roles")
    # `resp_commercial` : `partners: {view, add, change}`, non soumis a
    # MFA obligatoire — meme raisonnement que `commercial` ci-dessus.
    user.groups.add(Group.objects.get(name="resp_commercial"))
    client = _login_with_tenant(tenant, user)

    with use_tenant(tenant.id):
        partner = create_partner(tenant=tenant, name="PT12 SARL 3", roles=[Partner.ROLE_CLIENT])

    response = client.post(
        f"/partners/{partner.id}/contacts/new/",
        {"full_name": "Jean Dupont", "role": "", "email": "jean@example.com"},
    )
    assert response.status_code == 302
    with use_tenant(tenant.id):
        contact = PartnerContact.objects.get(partner=partner, full_name="Jean Dupont")

    response = client.post(
        f"/partners/{partner.id}/contacts/{contact.id}/",
        {"full_name": "Jean Dupont Bis", "role": "", "email": "jean@example.com"},
    )
    assert response.status_code == 302
    contact.refresh_from_db()
    assert contact.full_name == "Jean Dupont Bis"

    response = client.post(
        f"/partners/{partner.id}/contacts/{contact.id}/",
        {"action": "delete"},
    )
    assert response.status_code == 302
    contact.refresh_from_db()
    assert contact.is_active is False


def test_contact_create_forbidden_without_permission() -> None:
    tenant = Tenant.objects.create(code="PT12-4", name="PT12 Tenant 4")
    user = User.objects.create_user(email="pt12-4@example.com", password="Str0ngPassw0rd!23")
    call_command("load_roles")
    # `collaborateur` : `partners: {view}` seul (jamais `change`), non
    # soumis a MFA obligatoire — evite toute ambiguite avec la
    # redirection `/mfa/` qu'un role MFA-obligatoire non verifie
    # recevrait avant meme d'atteindre la vue.
    user.groups.add(Group.objects.get(name="collaborateur"))
    client = _login_with_tenant(tenant, user)

    with use_tenant(tenant.id):
        partner = create_partner(tenant=tenant, name="PT12 SARL 4", roles=[Partner.ROLE_CLIENT])

    response = client.post(f"/partners/{partner.id}/contacts/new/", {"full_name": "Refused"})
    assert response.status_code == 403


def test_role_scoped_contact_appears_only_on_its_own_tab() -> None:
    tenant = Tenant.objects.create(code="PT12-5", name="PT12 Tenant 5")
    user = User.objects.create_user(email="pt12-5@example.com", password="Str0ngPassw0rd!23")
    call_command("load_roles")
    user.groups.add(Group.objects.get(name="commercial"))
    client = _login_with_tenant(tenant, user)

    with use_tenant(tenant.id):
        partner = create_partner(
            tenant=tenant,
            name="PT12 SARL 5",
            roles=[Partner.ROLE_CLIENT, Partner.ROLE_SUPPLIER],
        )
        PartnerContact.objects.create(
            tenant=tenant,
            partner=partner,
            full_name="Achats Only",
            role=Partner.ROLE_SUPPLIER,
        )

    response = client.get(f"/partners/{partner.id}/")
    assert response.status_code == 200
    assert "Achats Only" in response.content.decode()
