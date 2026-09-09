"""T8 (bloc H, CON-1) — le journal des echanges, et le chemin retour.

**Le critere, sa seconde moitie** : « Depuis toute piece metier, l'etat de
ses echanges est atteignable en un clic, **et reciproquement depuis toute
ligne du journal**. »

**Ce que la mesure disait avant d'ecrire.** `apps/flows` n'avait ni
`views.py` ni `urls.py` : il n'existait aucun ecran de journal, donc aucune
ligne d'ou cliquer. La moitie « piece -> echanges » etait tenue au quart —
un fragment sur la seule facture. Ce lot construit l'ecran qui manquait.

**Pourquoi ces tests regardent le HTML rendu et pas le queryset.** Ce que
CON-1 exige est un LIEN sur lequel un exploitant clique. Un test qui
verifierait que la vue rend les bonnes lignes passerait encore le jour ou la
colonne cesserait d'etre cliquable — c'est-a-dire le jour ou le critere
serait viole.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django_otp.oath import totp

from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.services import mfa as mfa_service
from apps.core.tests.utils import grant_role, use_tenant
from apps.flows.models import FlwExchange, FlwLink
from apps.flows.operations import OP_PUBLISH_DATASET, OP_PUSH_DOCUMENT
from apps.flows.tests.factories import (
    FlwConnectorFactory,
    FlwExchangeFactory,
    FlwLinkFactory,
)

pytestmark = pytest.mark.django_db

JOURNAL = "/flows/"

#: L'identifiant d'une facture imaginaire. Le journal ne resout jamais la
#: piece — il construit son URL depuis le registre —, l'existence de la
#: facture n'est donc pas requise pour verifier le lien.
FACTURE_ID = "01a08600-0000-7000-8000-000000000001"


@pytest.fixture
def societe() -> Tenant:
    return Tenant.objects.create(code="T8-JRN", name="Journal des échanges")


def _client_admin(user: User) -> Client:
    """`admin` est soumis au MFA obligatoire (`CORE_MFA_REQUIRED_ROLES`) —
    meme sequence que `core/tests/test_admin_users.py`."""
    client = Client()
    reponse = client.post("/login/", {"email": user.email, "password": "Str0ngPassw0rd!23"})
    assert reponse.status_code == 302, reponse.content
    client.get("/mfa/")
    device = mfa_service.enroll_device(user)
    reponse = client.post("/mfa/", {"token": str(totp(device.bin_key)).zfill(6)})
    assert reponse.status_code == 302, reponse.content
    return client


@pytest.fixture
def admin(societe: Tenant) -> User:
    user = User.objects.create_user(email="admin-t8@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "admin")
    UserTenantMembership.objects.get_or_create(user=user, tenant=societe)
    return user


@pytest.fixture
def commercial(societe: Tenant) -> User:
    user = User.objects.create_user(email="commercial-t8@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "commercial")
    UserTenantMembership.objects.get_or_create(user=user, tenant=societe)
    return user


@pytest.fixture
def echanges(societe: Tenant) -> None:
    """Deux lignes qui disent tout : une qui designe une piece, une qui n'en
    designe aucune."""
    with use_tenant(societe.id):
        connecteur = FlwConnectorFactory(tenant=societe, code="fiscal-mg")
        liaison = FlwLinkFactory(tenant=societe, connector=connecteur, state=FlwLink.STATE_ACTIVE)
        FlwExchangeFactory(
            tenant=societe,
            link=liaison,
            operation=OP_PUSH_DOCUMENT,
            state=FlwExchange.STATE_ACCEPTED,
            document_type="accounting.AccMove",
            document_id=FACTURE_ID,
        )
        # Une publication planifiee (COM-3) : aucune piece designee. Etat
        # normal, et le cas que le critere ne couvre pas.
        FlwExchangeFactory(
            tenant=societe,
            link=liaison,
            operation=OP_PUBLISH_DATASET,
            state=FlwExchange.STATE_SENT,
            document_type="",
            document_id=None,
        )


def test_a_journal_line_links_back_to_its_document(admin: User, echanges: None) -> None:
    """**LE critere.** Le lien doit etre dans le HTML : c'est dessus qu'on
    clique."""
    reponse = _client_admin(admin).get(JOURNAL)

    assert reponse.status_code == 200
    contenu = reponse.content.decode()
    assert f"/accounting/{FACTURE_ID}/" in contenu, (
        "La ligne de journal ne renvoie pas vers sa pièce : CON-1 exige "
        "« réciproquement depuis toute ligne du journal »."
    )
    assert "Facture client" in contenu, (
        "La colonne « Pièce » affiche autre chose que le libellé lisible — "
        "le §10.3 refuse de remonter le vocabulaire technique tel quel."
    )
    assert "accounting.AccMove" not in contenu


def _corps_du_tableau(contenu: str) -> str:
    """Le `<tbody>` seul.

    Chercher dans la page entiere donnerait de faux verts : le code brut
    d'un etat figure legitimement dans le `<option value="accepte">` du
    filtre. Ce qu'on verifie ici, c'est ce qu'un exploitant LIT dans les
    lignes."""
    assert "<tbody>" in contenu
    return contenu.split("<tbody>", 1)[1].split("</tbody>", 1)[0]


def test_every_column_of_a_line_says_something(admin: User, echanges: None) -> None:
    """**Le défaut que ce test a été écrit pour attraper, et qui était bien
    là.**

    `core_extras.getattr` vaut `getattr(objet, clef, "")` : une colonne qui
    désigne un attribut inexistant s'affiche VIDE, sans lever, sans
    avertissement. La colonne « Destinataire » du journal l'était — et
    « Opération » et « État » affichaient les codes bruts, que le §10.3
    refuse de remonter tels quels.

    Aucun des autres tests ne le voyait : ils vérifiaient ce qu'ils
    s'attendaient à trouver, jamais ce qui devait figurer dans CHAQUE
    cellule."""
    corps = _corps_du_tableau(_client_admin(admin).get(JOURNAL).content.decode())

    assert "fiscal-mg" in corps, "La colonne « Destinataire » est vide."
    assert "Accepté" in corps, "L'état est affiché en code brut."
    assert "Émis" in corps
    assert "accepte" not in corps, "Le code brut de l'état est affiché à un comptable."
    assert "push_document" not in corps, "Le code brut de l'opération est affiché."


def test_a_line_without_a_document_says_so_instead_of_linking_nowhere(
    admin: User, echanges: None
) -> None:
    """Une publication planifiee ne designe aucune piece. Une cellule vide
    se lirait comme une donnee manquante ; un lien mort serait pire."""
    contenu = _client_admin(admin).get(JOURNAL).content.decode()

    assert "Aucune pièce rattachée" in contenu


def test_the_journal_is_closed_to_a_role_that_has_no_business_reading_it(
    commercial: User,
) -> None:
    """Un echange dit vers QUI une piece est partie, avec quelle empreinte et
    quel verdict : donnee d'exploitation et de preuve, pas donnee de travail
    quotidien. `rbac_policy` ne l'ouvre qu'a `admin` et `direction`."""
    client = Client()
    reponse = client.post("/login/", {"email": commercial.email, "password": "Str0ngPassw0rd!23"})
    assert reponse.status_code == 302

    assert client.get(JOURNAL).status_code == 403


def test_the_state_filter_narrows_the_journal(admin: User, echanges: None) -> None:
    """§10.2 : « recherche par piece, tiers, statut, periode »."""
    client = _client_admin(admin)

    accepte = client.get(JOURNAL, {"state": FlwExchange.STATE_ACCEPTED}).content.decode()
    assert "Facture client" in accepte
    assert "Aucune pièce rattachée" not in accepte

    emis = client.get(JOURNAL, {"state": FlwExchange.STATE_SENT}).content.decode()
    assert "Aucune pièce rattachée" in emis
    assert f"/accounting/{FACTURE_ID}/" not in emis


def test_the_connector_filter_narrows_the_journal(admin: User, echanges: None) -> None:
    client = _client_admin(admin)

    assert "Facture client" in client.get(JOURNAL, {"connector": "fiscal-mg"}).content.decode()
    absent = client.get(JOURNAL, {"connector": "un-connecteur-absent"}).content.decode()
    assert "Facture client" not in absent


def test_the_document_filter_is_the_link_the_fragment_points_to(
    admin: User, echanges: None
) -> None:
    """C'est l'URL que `document_exchange_panel` construit : le premier sens
    de CON-1 se referme sur le second."""
    contenu = _client_admin(admin).get(JOURNAL, {"document_id": FACTURE_ID}).content.decode()

    assert "Facture client" in contenu
    assert "Aucune pièce rattachée" not in contenu


def test_a_malformed_filter_empties_the_journal_instead_of_breaking_it(
    admin: User, echanges: None
) -> None:
    """Un journal qui rendrait 500 sur `?document_id=oops` serait
    inutilisable precisement le jour ou on le consulte en urgence — la
    classe de defaut que le lot T4bis a fermee partout ailleurs."""
    client = _client_admin(admin)

    assert client.get(JOURNAL, {"document_id": "pas-un-uuid"}).status_code == 200
    assert client.get(JOURNAL, {"since": "hier"}).status_code == 200
    assert client.get(JOURNAL, {"until": "31/02/2026"}).status_code == 200


def test_the_journal_is_reachable_from_the_sidebar(admin: User, echanges: None) -> None:
    """**Sans entree de menu, l'ecran existerait et personne ne pourrait
    l'atteindre.**

    C'est le motif « rien de decoratif », rencontre a chaque lot de cette
    vague — vu AVANT d'ecrire cette fois, par la mesure : `flows`
    n'appartenait a aucun des sept groupes de `_MENU_GROUPS`."""
    # `follow=True` : la racine redirige vers le launchpad, et c'est la
    # page rendue — pas la redirection — qui porte la barre latérale.
    contenu = _client_admin(admin).get("/", follow=True).content.decode()

    assert "Journal des échanges" in contenu
    assert f'href="{JOURNAL}"' in contenu
