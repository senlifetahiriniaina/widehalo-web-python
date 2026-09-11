"""C-4 — une ligne de liste se lit, et dit la même chose que sa carte.

Le commanditaire demande que « le statut d'une ligne d'opération existe
aussi » sur les listes simples. Il existait : une colonne « Statut » est
déclarée sur les cinq listes d'opérations des quatre modules. **Mais la
mesure a montré ce que la cellule contenait vraiment** — `draft`, le code
technique anglais, dans une interface française ; `None` pour un champ
vide ; et, pour une colonne appuyée sur une propriété, un en-tête de tri
qui rendait 500 au premier clic.

C'est la quatrième fois de ce chantier qu'un instrument compte une
PRÉSENCE là où l'exigence porte sur une VALEUR : ma mesure précédente
avait compté les en-têtes « Statut/État/Étape » et conclu que la demande
était déjà tenue.

Les quatre propriétés vérifiées ici portent donc sur ce qui arrive au
navigateur, jamais sur la déclaration de colonne."""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
import uuid

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.tests.utils import grant_module_access, use_tenant
from apps.sales.services.orders import create_order
from django.test import Client

pytestmark = pytest.mark.django_db


def _client_et_societe(code: str, courriel: str) -> tuple[Client, Tenant]:
    tenant = Tenant.objects.create(code=code, name="Societe lisible")
    user = User.objects.create_user(email=courriel, password="Str0ngPassw0rd!23")
    grant_module_access(user, "sales", "accounting", "logistics", "partners")
    UserTenantMembership.objects.get_or_create(
        user=user, tenant=tenant, defaults={"is_default": True}
    )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant


def _cellules(contenu: str) -> list[str]:
    return [
        re.sub(r"<[^>]+>|\s+", " ", cellule).strip()
        for cellule in re.findall(r"<td[^>]*>(.*?)</td>", contenu, re.S)
    ]


def test_a_closed_set_field_shows_its_label_not_its_code() -> None:
    """`draft` est un code de base ; « Brouillon » est ce que l'exploitant
    doit lire. Django expose déjà `get_FOO_display()` pour ces champs."""
    client, tenant = _client_et_societe("LIS1", "lis1@example.com")
    with use_tenant(tenant.id):
        commande = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        assert commande.state == "draft", "Le jeu d'essai ne part plus de l'état attendu."

    cellules = _cellules(client.get("/sales/orders/?presentation=liste").content.decode())
    assert "Brouillon" in cellules, f"La liste ne montre pas le libellé de l'état : {cellules}"
    assert "draft" not in cellules, f"La liste montre encore le code technique : {cellules}"


def test_the_export_says_what_the_screen_says() -> None:
    """Un fichier qui dirait `draft` là où la page dit « Brouillon »
    obligerait le lecteur à tenir la correspondance de tête."""
    client, tenant = _client_et_societe("LIS2", "lis2@example.com")
    with use_tenant(tenant.id):
        create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())

    reponse = client.get("/sales/orders/", {"export": "csv"})
    assert reponse["Content-Disposition"].startswith("attachment"), (
        "L'export ne rend plus un fichier."
    )
    lignes = list(csv.reader(io.StringIO(reponse.content.decode())))
    assert any("Brouillon" in ligne for ligne in lignes[1:]), (
        f"L'export ne porte pas le libellé de l'état : {lignes}"
    )


def test_an_empty_field_is_empty_and_never_the_word_none() -> None:
    """Une commande sans commercial affichait `None` — le `repr` Python
    d'une absence, servi tel quel."""
    client, tenant = _client_et_societe("LIS3", "lis3@example.com")
    with use_tenant(tenant.id):
        commande = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        assert commande.salesperson is None, "Le jeu d'essai porte désormais un commercial."

    cellules = _cellules(client.get("/sales/orders/?presentation=liste").content.decode())
    assert "None" not in cellules, f"Une cellule vide s'affiche « None » : {cellules}"


def test_a_property_column_offers_no_sort_link_and_never_500() -> None:
    """Mesuré avant correctif : `/partners/?sort=roles_display` levait
    `FieldError` — un 500 atteignable d'un clic sur l'en-tête « Rôles »,
    puisque chaque en-tête est un lien de tri sur sa propre clef."""
    client, _tenant = _client_et_societe("LIS4", "lis4@example.com")

    contenu = client.get("/partners/").content.decode()
    entete = re.search(r"<th[^>]*>(?:(?!</th>).)*Rôles(?:(?!</th>).)*</th>", contenu, re.S)
    assert entete is not None, "L'en-tête « Rôles » a disparu de la liste des tiers."
    assert "sort=roles_display" not in entete.group(0), (
        "L'en-tête propose un tri que la base ne sait pas exécuter."
    )

    assert client.get("/partners/", {"sort": "roles_display"}).status_code == 200
    assert client.get("/partners/", {"sort": "n_importe_quoi"}).status_code == 200


def test_the_list_cell_and_the_card_say_the_same_word() -> None:
    """Les deux présentations lisent le même champ : la cellule par le
    rendu générique, la carte par `statut_operationnel`. Un écran qui se
    contredirait serait pire que pas de kanban."""
    client, tenant = _client_et_societe("LIS5", "lis5@example.com")
    with use_tenant(tenant.id):
        create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())

    cellules = _cellules(client.get("/sales/orders/?presentation=liste").content.decode())
    contenu_kanban = client.get("/sales/orders/?presentation=kanban").content.decode()
    cartes = [
        re.sub(r"<[^>]+>|\s+", " ", carte).strip()
        for carte in re.findall(r'<article class="card".*?</article>', contenu_kanban, re.S)
    ]
    assert cartes, "Le kanban ne rend aucune carte."
    assert "Brouillon" in cellules and "Brouillon" in cartes[0], (
        f"La liste dit {cellules}, la carte dit {cartes[0]} — les deux vues divergent."
    )
    assert "En attente" not in cartes[0], (
        "La carte répète le nom de sa colonne : la ligne n'apprend rien de plus "
        f"que l'en-tête qui la surplombe ({cartes[0]})."
    )
