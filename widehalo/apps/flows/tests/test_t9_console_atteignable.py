"""T9 — les écrans de gouvernance sont atteignables, et fermés à qui n'a
rien à y décider.

**Pourquoi ce fichier existe.** Ce lot corrige, sur quatre mécanismes, du
code écrit et documenté que rien n'invoquait. Livrer des écrans que personne
ne peut atteindre reproduirait exactement le défaut en le corrigeant — et
c'est un piège dans lequel ce dépôt est déjà tombé : `apps.quality` avait
été livré sans vue, sans URL et sans entrée de menu, et l'audit l'a compté
comme un module inatteignable depuis le produit.

**Le contrôle d'accès n'est pas celui du journal.** Le journal se lit avec
`flows.view_flwexchange` ; la console DÉCIDE — on consent, on plafonne, on
révoque, on rejoue — et demande donc `flows.change_flwlink`. Un rôle qui
peut lire ce qui est parti n'a pas pour autant à autoriser ce qui partira.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse
from django_otp.oath import totp

from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.services import mfa as mfa_service
from apps.core.tests.utils import grant_role, use_tenant
from apps.flows.models import FlwLink
from apps.flows.tests.factories import FlwConnectorFactory, FlwLinkFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def societe() -> Tenant:
    return Tenant.objects.create(code="T9-CONSOLE", name="Console atteignable")


@pytest.fixture
def liaison(societe: Tenant) -> FlwLink:
    with use_tenant(societe.id):
        connecteur = FlwConnectorFactory(tenant=societe, code="dgi")
        return FlwLinkFactory(tenant=societe, connector=connecteur)


@pytest.fixture
def admin(societe: Tenant) -> User:
    user = User.objects.create_user(email="admin-console@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "admin")
    UserTenantMembership.objects.get_or_create(user=user, tenant=societe)
    return user


@pytest.fixture
def commercial(societe: Tenant) -> User:
    user = User.objects.create_user(
        email="commercial-console@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(user, "commercial")
    UserTenantMembership.objects.get_or_create(user=user, tenant=societe)
    return user


def _client_admin(user: User) -> Client:
    client = Client()
    reponse = client.post("/login/", {"email": user.email, "password": "Str0ngPassw0rd!23"})
    assert reponse.status_code == 302, reponse.content
    client.get("/mfa/")
    device = mfa_service.enroll_device(user)
    reponse = client.post("/mfa/", {"token": str(totp(device.bin_key)).zfill(6)})
    assert reponse.status_code == 302, reponse.content
    return client


def test_the_console_is_reachable_from_the_sidebar(admin: User, liaison: FlwLink) -> None:
    """**Sans entrée de menu, les écrans existeraient à des URL que personne
    ne connaît.** C'est le motif que ce lot corrige sur quatre mécanismes ;
    le reproduire ici serait singulier."""
    contenu = _client_admin(admin).get("/", follow=True).content.decode()

    assert "Raccordements et plafonds" in contenu
    assert f'href="{reverse("flows:link_list")}"' in contenu


def test_the_link_list_leads_to_the_governance_screen(admin: User, liaison: FlwLink) -> None:
    """La liste n'existe que pour mener quelque part : sans le lien, elle
    afficherait des raccordements sans permettre d'en décider."""
    contenu = _client_admin(admin).get(reverse("flows:link_list")).content.decode()

    assert reverse("flows:link_console", args=[liaison.id]) in contenu
    assert reverse("flows:replay_panel") in contenu


def test_the_governance_screen_shows_the_four_informations(admin: User, liaison: FlwLink) -> None:
    """§9.1 — l'écran affiche EN CLAIR, avant validation, ce qui sortira,
    vers qui, dans quel pays et pour quelle durée."""
    contenu = (
        _client_admin(admin).get(reverse("flows:link_console", args=[liaison.id])).content.decode()
    )

    assert "Ce qui sortira de chez vous" in contenu
    assert "Vers quel tiers" in contenu
    assert "Dans quel pays" in contenu
    assert "Durée de conservation chez le tiers" in contenu
    assert "Plafond mensuel" in contenu


def test_the_replay_panel_is_reachable(admin: User, liaison: FlwLink) -> None:
    contenu = _client_admin(admin).get(reverse("flows:replay_panel")).content.decode()

    assert "Rejeu supervisé" in contenu
    assert "Estimer le rejeu" in contenu


def test_a_role_that_decides_nothing_is_refused(commercial: User, liaison: FlwLink) -> None:
    """Un commercial peut légitimement ignorer qu'un canal existe ; il n'a
    en aucun cas à décider de ce qui sort de l'entreprise."""
    client = Client()
    reponse = client.post("/login/", {"email": commercial.email, "password": "Str0ngPassw0rd!23"})
    assert reponse.status_code == 302

    assert client.get(reverse("flows:link_list")).status_code == 403
    assert client.get(reverse("flows:link_console", args=[liaison.id])).status_code == 403
    assert client.get(reverse("flows:replay_panel")).status_code == 403
