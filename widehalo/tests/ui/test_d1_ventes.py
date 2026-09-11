"""D-1 (Ventes) — ce que les ecrans de vente AFFICHENT.

Les ecrans de `sales` etaient gardes (C-1), uniformes (C-2) et dotes d'un
kanban (C-4) ; ce qu'ils montraient dedans ne se lisait pas. Trois surfaces
rendaient l'identifiant technique du tiers — la liste des commandes et les
deux fiches — et comme ce sont des UUIDv7, prefixes par un horodatage, deux
lignes du meme jour partageaient leurs quatorze premiers caracteres : la
colonne ne distinguait rien.

Chaque test ci-dessous echoue si on revient en arriere ; aucun ne se
contente d'un code de statut."""

from __future__ import annotations

import csv
import datetime as dt
import io
import uuid
from decimal import Decimal

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.partners.services.onboarding import create_partner
from apps.sales.models import SalesOrder, SalesQuotation
from apps.sales.services.orders import add_order_line, create_order
from apps.sales.services.quotations import add_quotation_line, create_quotation
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

pytestmark = pytest.mark.django_db


@pytest.fixture
def ventes():
    """Une societe, trois tiers NOMMES, une commande et un devis par tiers."""
    tenant = Tenant.objects.create(code="D1-SALES", name="D1 Sales Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="d1-sales@example.com", password="Str0ngPassw0rd!23")
        grant_role(user, "commercial")
        tiers = [
            create_partner(tenant=tenant, name=f"Client D1 n{numero} SARL", roles=["client"])
            for numero in range(1, 4)
        ]
        commandes = []
        for partenaire in tiers:
            commande = create_order(tenant=tenant, partner_id=partenaire.id, date=dt.date.today())
            add_order_line(
                commande,
                description="Ligne",
                qty=Decimal(1),
                unit_price=Decimal(1000),
                is_custom=True,
            )
            commandes.append(commande)
        devis = create_quotation(tenant=tenant, partner_id=tiers[0].id, date=dt.date.today())
        add_quotation_line(
            devis, description="Ligne", qty=Decimal(1), unit_price=Decimal(1000), is_custom=True
        )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, tiers, commandes, devis


def test_la_liste_des_commandes_nomme_le_tiers_et_ne_montre_aucun_uuid(ventes) -> None:
    client, _tenant, tiers, _commandes, _devis = ventes
    contenu = client.get("/sales/orders/?presentation=liste").content.decode()
    for partenaire in tiers:
        assert partenaire.name in contenu, f"{partenaire.name} absent de la liste"
        assert str(partenaire.id) not in contenu, "l'UUID du tiers est encore rendu"


def test_le_kanban_ne_montre_aucun_identifiant_de_tiers(ventes) -> None:
    """**Mesure, pas supposition** : la carte du kanban rend le `__str__` du
    document et son statut operationnel — jamais une colonne declaree. Elle
    ne nomme donc pas le tiers, et n'affichait pas non plus son UUID. Ce
    test fixe l'etat constate pour qu'un futur sous-titre de carte soit un
    choix, et non une fuite d'identifiant."""
    client, _tenant, tiers, _commandes, _devis = ventes
    contenu = client.get("/sales/orders/?presentation=kanban").content.decode()
    for partenaire in tiers:
        assert str(partenaire.id) not in contenu


def test_l_export_csv_porte_le_nom_du_tiers_comme_sa_page(ventes) -> None:
    """Le fichier ne contredit pas l'ecran qui l'a produit — D-0 a aligne
    les EN-TETES, D-1 aligne les CELLULES."""
    client, _tenant, tiers, _commandes, _devis = ventes
    reponse = client.get("/sales/orders/?export=csv")
    assert reponse.status_code == 200
    lignes = list(csv.reader(io.StringIO(reponse.content.decode("utf-8"))))
    entete, corps = lignes[0], lignes[1:]
    colonne = entete.index("Partenaire")
    noms_rendus = {ligne[colonne] for ligne in corps}
    assert noms_rendus == {partenaire.name for partenaire in tiers}


def test_les_deux_fiches_nomment_le_tiers(ventes) -> None:
    client, _tenant, tiers, commandes, devis = ventes
    fiche_commande = client.get(f"/sales/orders/{commandes[0].id}/").content.decode()
    assert tiers[0].name in fiche_commande
    assert str(tiers[0].id) not in fiche_commande

    fiche_devis = client.get(f"/sales/{devis.id}/").content.decode()
    assert tiers[0].name in fiche_devis
    assert str(tiers[0].id) not in fiche_devis


def test_une_fiche_dont_le_tiers_a_disparu_le_dit(ventes) -> None:
    """Un tiers supprime ne fait pas reapparaitre son UUID : l'ecran ecrit
    que le tiers est introuvable. Sans cette branche, le repli naturel
    serait de re-afficher l'identifiant — c'est-a-dire le defaut d'origine."""
    client, tenant, _tiers, _commandes, _devis = ventes
    with use_tenant(tenant.id):
        orpheline = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
    contenu = client.get(f"/sales/orders/{orpheline.id}/").content.decode()
    assert "tiers introuvable" in contenu
    assert str(orpheline.partner_id) not in contenu


def test_le_nom_des_tiers_coute_une_seule_requete_quel_que_soit_le_nombre_de_lignes(
    ventes,
) -> None:
    """La propriete qui distingue une lecture groupee d'un appel par ligne.

    Trois commandes, trois tiers distincts : si le nom etait resolu ligne a
    ligne, `partners_partner` serait lue trois fois. La mesure porte donc
    sur le NOMBRE DE LECTURES de cette table, jamais sur le total de
    requetes de la page — qui depend de tout le reste de l'ecran."""
    client, tenant, tiers, _commandes, _devis = ventes
    with use_tenant(tenant.id):
        for numero in range(4, 9):
            autre = create_partner(
                tenant=tenant, name=f"Client D1 n{numero} SARL", roles=["client"]
            )
            create_order(tenant=tenant, partner_id=autre.id, date=dt.date.today())

    with CaptureQueriesContext(connection) as requetes:
        reponse = client.get("/sales/orders/?presentation=liste")
    assert reponse.status_code == 200
    lectures = [
        requete["sql"]
        for requete in requetes.captured_queries
        if "partners_partner" in requete["sql"]
        and requete["sql"].lstrip().upper().startswith("SELECT")
    ]
    assert len(lectures) == 1, f"{len(lectures)} lectures du referentiel tiers : " + "\n".join(
        lectures
    )


def test_les_montants_des_deux_listes_sont_en_ariary_et_en_chasse_fixe(ventes) -> None:
    """Le devis porte `amount_total` en devise du document et
    `amount_total_mga` converti : seule la seconde peut s'annoncer « MGA »."""
    client, *_ = ventes
    for chemin in ("/sales/?presentation=liste", "/sales/orders/?presentation=liste"):
        contenu = client.get(chemin).content.decode()
        assert "Montant (MGA)" in contenu, chemin
        assert "col-num" in contenu, f"{chemin} : la colonne de montant n'est pas en chasse fixe"


@pytest.mark.parametrize(
    "modele,champ",
    [
        (SalesOrder, "state"),
        (SalesQuotation, "state"),
    ],
)
def test_les_libelles_d_etat_sont_traduisibles(modele, champ) -> None:
    """`gettext_lazy`, pas `gettext` : dans un module de modeles, la forme
    eager fige la traduction a l'import du processus — la premiere langue
    chargee gagne pour tout le monde. `sales/models.py` etait le seul des
    treize `models.py` du depot a l'employer."""
    libelles = [libelle for _code, libelle in modele._meta.get_field(champ).choices]
    assert libelles, f"{modele.__name__}.{champ} n'a aucun libelle"
    for libelle in libelles:
        assert not isinstance(libelle, str), (
            f"{modele.__name__}.{champ} : {libelle!r} est une chaine nue, donc jamais traduite"
        )
