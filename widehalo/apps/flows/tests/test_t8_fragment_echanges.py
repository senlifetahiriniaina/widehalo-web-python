"""T8 (bloc H, CON-1) — le fragment d'echanges, sur les quatre pieces.

**Le critere, sa premiere moitie** : « Depuis TOUTE piece metier, l'etat de
ses echanges est atteignable en un clic. »

**Ce que la mesure disait avant d'ecrire.** Les deux fragments de T4
(`flows/_exchange_badge.html`, `flows/_waiting_banner.html`) existaient et
n'etaient inclus QUE dans `templates/accounting/detail.html` — la facture.
Un quart du critere. Et ils ne sont pas reutilisables tels quels : ils
attendent `fiscal_state`/`fiscal_state_display`, c'est-a-dire l'axe FISCAL
d'une facture (EFA-6). Une commande de vente et une fiche tiers n'ont aucun
etat fiscal ; les brancher dessus n'afficherait rien.

**Pourquoi ces tests rendent les ECRANS REELS.** Un gabarit qui inclut le
fragment mais dont la vue ne remplit pas le contexte rend le vide — sans
erreur, sans avertissement, et en ayant l'air correct a la relecture. C'est
exactement la forme du defaut que cette vague rencontre a chaque lot. Seul
un rendu de bout en bout, vue comprise, le montre.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.test import Client
from django.utils import timezone
from django_otp.oath import totp

from apps.accounting.models import AccMove
from apps.accounting.tests.factories import AccMoveFactory
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.services import mfa as mfa_service
from apps.core.tests.utils import grant_role, use_tenant
from apps.flows.exchange_display import badge_class_for_state
from apps.flows.models import FlwExchange, FlwLink
from apps.flows.operations import OP_PUSH_DOCUMENT, OP_QUERY_REFERENCE
from apps.flows.services.public import document_exchange_panel, list_exchanges_for_document
from apps.flows.tests.factories import (
    FlwConnectorFactory,
    FlwExchangeFactory,
    FlwLinkFactory,
)
from apps.partners.tests.factories import PartnerFactory
from apps.sales.tests.factories import SalesOrderFactory, SalesQuotationFactory

pytestmark = pytest.mark.django_db

#: Les quatre couleurs du §10.2, ecrites ICI et non importees du module
#: qu'elles surveillent — un jeu ferme ne se verifie jamais contre sa propre
#: source (lecon F60 du lot T6).
QUATRE_COULEURS = {"b-neutral", "b-pending", "b-success", "b-fail"}


@pytest.fixture
def societe() -> Tenant:
    return Tenant.objects.create(code="T8-FRG", name="Fragment d'échanges")


@pytest.fixture
def admin(societe: Tenant) -> User:
    user = User.objects.create_user(email="admin-frg@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "admin")
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


def _liaison(societe: Tenant) -> FlwLink:
    """UNE liaison par societe, reutilisee.

    `uniq_flw_connector_code_per_tenant` refuse deux connecteurs du meme
    code — et c'est la bonne contrainte : deux echanges d'une meme piece
    partent par la MEME liaison, pas par deux jumelles."""
    existante = FlwLink.objects.filter(connector__code="fiscal-mg").first()
    if existante is not None:
        return existante
    connecteur = FlwConnectorFactory(tenant=societe, code="fiscal-mg")
    return FlwLinkFactory(tenant=societe, connector=connecteur, state=FlwLink.STATE_ACTIVE)


def _echange(societe: Tenant, *, document_type: str, document_id, **kwargs) -> FlwExchange:
    return FlwExchangeFactory(
        tenant=societe,
        link=_liaison(societe),
        document_type=document_type,
        document_id=document_id,
        **kwargs,
    )


# --- Les quatre ecrans -------------------------------------------------------


def test_the_invoice_screen_shows_the_state_of_its_exchanges(admin: User, societe: Tenant) -> None:
    with use_tenant(societe.id):
        facture = AccMoveFactory(tenant=societe, move_type=AccMove.TYPE_CUSTOMER_INVOICE)
        _echange(
            societe,
            document_type="accounting.AccMove",
            document_id=facture.id,
            operation=OP_PUSH_DOCUMENT,
            state=FlwExchange.STATE_ACCEPTED,
        )

    contenu = _client_admin(admin).get(f"/accounting/{facture.id}/").content.decode()

    assert "Échanges avec les tiers" in contenu
    assert "Accepté" in contenu
    assert "fiscal-mg" in contenu


def test_the_sales_order_screen_shows_the_state_of_its_exchanges(
    admin: User, societe: Tenant
) -> None:
    """La commande de vente n'a AUCUN etat fiscal — c'est precisement
    pourquoi le fragment de T4 ne pouvait pas servir ici."""
    with use_tenant(societe.id):
        commande = SalesOrderFactory(tenant=societe)
        _echange(
            societe,
            document_type="sales.SalesOrder",
            document_id=commande.id,
            operation=OP_PUSH_DOCUMENT,
            state=FlwExchange.STATE_ACCEPTED,
        )

    contenu = _client_admin(admin).get(f"/sales/orders/{commande.id}/").content.decode()

    assert "Échanges avec les tiers" in contenu
    assert "Accepté" in contenu


def test_the_quotation_screen_shows_the_state_of_its_exchanges(
    admin: User, societe: Tenant
) -> None:
    with use_tenant(societe.id):
        devis = SalesQuotationFactory(tenant=societe)
        _echange(
            societe,
            document_type="sales.SalesQuotation",
            document_id=devis.id,
            operation=OP_PUSH_DOCUMENT,
            state=FlwExchange.STATE_ACCEPTED,
        )

    contenu = _client_admin(admin).get(f"/sales/{devis.id}/").content.decode()

    assert "Échanges avec les tiers" in contenu


def test_the_partner_screen_shows_the_state_of_its_exchanges(admin: User, societe: Tenant) -> None:
    """La fiche tiers recoit des echanges par OP8 (verification
    d'identifiant fiscal, T3). C'etait le seul module qui interrogeait le
    hub sans que rien n'en montre le resultat la ou le tiers se consulte."""
    with use_tenant(societe.id):
        tiers = PartnerFactory(tenant=societe)
        _echange(
            societe,
            document_type="partners.Partner",
            document_id=tiers.id,
            operation=OP_QUERY_REFERENCE,
            state=FlwExchange.STATE_ACCEPTED,
        )

    contenu = _client_admin(admin).get(f"/partners/{tiers.id}/").content.decode()

    assert "Échanges avec les tiers" in contenu


# --- Ce que le fragment affiche ---------------------------------------------


def test_a_waiting_exchange_says_what_happens_next_and_when(admin: User, societe: Tenant) -> None:
    """**§10.1, l'exigence la plus forte de la phase** : « tout etat
    d'attente affiche ce qui va se passer ensuite ET QUAND ».

    Un bandeau qui dirait seulement « en attente » ferait appeler le support
    pour une situation parfaitement normale."""
    prochaine = timezone.now() + dt.timedelta(hours=2)
    with use_tenant(societe.id):
        facture = AccMoveFactory(tenant=societe, move_type=AccMove.TYPE_CUSTOMER_INVOICE)
        _echange(
            societe,
            document_type="accounting.AccMove",
            document_id=facture.id,
            operation=OP_PUSH_DOCUMENT,
            state=FlwExchange.STATE_TO_RETRY,
            next_attempt_at=prochaine,
        )

    contenu = _client_admin(admin).get(f"/accounting/{facture.id}/").content.decode()

    assert "Nouvelle tentative à" in contenu
    assert prochaine.strftime("%Hh%M") in contenu


def test_a_document_without_exchanges_shows_nothing_at_all(admin: User, societe: Tenant) -> None:
    """L'immense majorite des pieces n'ont jamais donne lieu a un echange.
    Afficher « aucun echange » sur chacune ajouterait un bloc vide a tous
    les ecrans du produit pour ne rien apprendre."""
    with use_tenant(societe.id):
        facture = AccMoveFactory(tenant=societe, move_type=AccMove.TYPE_CUSTOMER_INVOICE)

    contenu = _client_admin(admin).get(f"/accounting/{facture.id}/").content.decode()

    assert "Échanges avec les tiers" not in contenu


def test_the_label_is_always_there_and_the_colour_only_doubles_it(
    societe: Tenant,
) -> None:
    """**§10.2, mot pour mot** : « quatre couleurs au maximum, un libelle
    toujours present — la couleur seule ne porte jamais l'information ».

    La mesure qui a decide de la conception : le filtre generique du depot
    (`core_extras.state_badge_class`) se trompe sur SIX des neuf etats du
    hub — `accepte` et `rejete` y tombent tous deux en gris, c'est-a-dire
    que le seul etat appelant un geste s'afficherait comme n'en appelant
    aucun."""
    with use_tenant(societe.id):
        facture = AccMoveFactory(tenant=societe, move_type=AccMove.TYPE_CUSTOMER_INVOICE)
        for etat in (FlwExchange.STATE_ACCEPTED, FlwExchange.STATE_REJECTED):
            _echange(
                societe,
                document_type="accounting.AccMove",
                document_id=facture.id,
                operation=OP_PUSH_DOCUMENT,
                state=etat,
            )

        lignes = list_exchanges_for_document(
            societe, document_type="accounting.AccMove", document_id=facture.id
        )

    par_etat = {ligne["state"]: ligne for ligne in lignes}
    assert par_etat[FlwExchange.STATE_ACCEPTED]["state_badge"] == "b-success"
    assert par_etat[FlwExchange.STATE_REJECTED]["state_badge"] == "b-fail"
    for ligne in lignes:
        assert ligne["state_badge"] in QUATRE_COULEURS
        assert ligne["state_display"], "Un libellé est toujours présent."
        assert ligne["state_display"] != ligne["state"], (
            "Le libellé affiché est le code brut : §10.3 refuse de remonter "
            "le vocabulaire technique tel quel."
        )


def test_the_four_colours_are_not_five(societe: Tenant) -> None:
    """Le plafond du cahier, verifie sur les NEUF etats et pas seulement sur
    ceux qu'un test a semes."""
    couleurs = {badge_class_for_state(code) for code, _libelle in FlwExchange.STATE_CHOICES}
    assert couleurs <= QUATRE_COULEURS
    assert len(QUATRE_COULEURS) == 4


def test_the_panel_points_at_the_journal_filtered_on_this_document(
    societe: Tenant,
) -> None:
    """Le premier sens de CON-1 se referme sur le second : le lien du
    fragment est l'URL que le journal sait filtrer."""
    with use_tenant(societe.id):
        facture = AccMoveFactory(tenant=societe, move_type=AccMove.TYPE_CUSTOMER_INVOICE)
        _echange(
            societe,
            document_type="accounting.AccMove",
            document_id=facture.id,
            operation=OP_PUSH_DOCUMENT,
            state=FlwExchange.STATE_ACCEPTED,
        )
        panneau = document_exchange_panel(
            societe, document_type="accounting.AccMove", document_id=facture.id
        )

    assert panneau["document_exchanges_link"] == f"/flows/?document_id={facture.id}"
    assert len(panneau["document_exchanges"]) == 1
