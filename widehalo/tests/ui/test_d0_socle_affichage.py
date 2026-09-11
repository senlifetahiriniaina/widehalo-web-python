"""D-0 — le socle d'affichage : ce que l'écran montre, et ce que l'export dit.

Trois défauts mesurés, tous antérieurs aux lots C et invisibles jusqu'à ce
que l'audit regarde les VALEURS plutôt que les déclarations :

1. **Trois heures de retard sur tout le produit.** `TIME_ZONE = "UTC"`,
   `DISPLAY_TIME_ZONE = "Indian/Antananarivo"`, et aucun
   `timezone.activate()` nulle part dans le dépôt.
2. **Un export qui contredit sa propre page** : en-têtes en noms de champs
   là où l'écran affiche des libellés, dates en ISO, décimales à point.
3. Le kanban chargeait l'intégralité du jeu de données, ce que le cahier
   interdit nommément (l.505).
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import uuid

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.models.workflow import ApprovalRequest, ApprovalRule
from apps.core.tests.utils import grant_module_access, grant_role, use_tenant
from django.contrib.contenttypes.models import ContentType
from django.test import Client

pytestmark = pytest.mark.django_db


def _client(tenant: Tenant, user: User) -> Client:
    UserTenantMembership.objects.get_or_create(
        user=user, tenant=tenant, defaults={"is_default": True}
    )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def test_a_displayed_time_is_the_one_in_antananarivo() -> None:
    """08:30 à Antananarivo ne s'affiche pas « 05:30 ».

    Le réglage `DISPLAY_TIME_ZONE` existait depuis toujours et n'était lu
    par aucun code d'affichage : tout horodatage du produit portait trois
    heures de retard."""
    tenant = Tenant.objects.create(code="D0TZ", name="Societe fuseau")
    user = User.objects.create_user(email="d0-tz@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "magasinier")

    with use_tenant(tenant.id):
        regle = ApprovalRule.objects.create(
            tenant=tenant,
            content_type=ContentType.objects.get_for_model(Tenant),
            name="Règle témoin",
            approver_role="magasinier",
        )
        demande = ApprovalRequest.objects.create(
            tenant=tenant,
            rule=regle,
            content_type=ContentType.objects.get_for_model(Tenant),
            object_id=str(tenant.id),
            requested_by=user,
        )
        # 05:30 UTC = 08:30 à Antananarivo (UTC+3, sans heure d'été).
        ApprovalRequest.objects.filter(pk=demande.pk).update(
            created_at=dt.datetime(2026, 1, 15, 5, 30, tzinfo=dt.UTC)
        )

    contenu = _client(tenant, user).get("/approvals/").content.decode()
    assert "08:30" in contenu, (
        "L'heure affichée n'est pas celle d'Antananarivo : le fuseau d'affichage n'est pas activé."
    )
    assert "05:30" not in contenu, "L'écran affiche encore l'heure UTC."


def _commande(tenant: Tenant) -> None:
    from apps.sales.services.orders import create_order

    with use_tenant(tenant.id):
        create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date(2026, 1, 15))


def test_the_export_header_carries_labels_not_field_names() -> None:
    """Le même bouton produisait un PDF titré en libellés et un CSV en noms
    de champs. Un exploitant ne lit pas `amount_total_mga`."""
    tenant = Tenant.objects.create(code="D0EX", name="Societe export")
    user = User.objects.create_user(email="d0-ex@example.com", password="Str0ngPassw0rd!23")
    grant_module_access(user, "sales")
    _commande(tenant)

    reponse = _client(tenant, user).get("/sales/orders/", {"export": "csv"})
    entete = next(csv.reader(io.StringIO(reponse.content.decode())))
    assert "Reference" in entete or "Référence" in entete, (
        f"L'en-tête de l'export ne porte pas les libellés de l'écran : {entete}"
    )
    assert "amount_total_mga" not in entete, (
        f"L'en-tête de l'export porte encore des noms de champs : {entete}"
    )


def test_the_export_writes_numbers_like_the_screen() -> None:
    """**Une première version de ce test ne mesurait rien.** Elle cherchait
    une date en ISO dans l'export des commandes — or cette liste ne déclare
    aucune colonne de date : l'assertion était vraie quoi qu'il arrive. Le
    séparateur décimal, lui, est bien dans le fichier : l'écran affiche
    « 0,0000 » sous locale française, et `str(Decimal)` écrivait
    « 0.0000 »."""
    tenant = Tenant.objects.create(code="D0FM", name="Societe format")
    user = User.objects.create_user(email="d0-fm@example.com", password="Str0ngPassw0rd!23")
    grant_module_access(user, "sales")
    _commande(tenant)

    reponse = _client(tenant, user).get("/sales/orders/", {"export": "csv"})
    corps = reponse.content.decode()
    assert "0.0000" not in corps, (
        "L'export écrit encore ses décimales avec un point, alors que l'écran affiche "
        "une virgule : le fichier contredit sa propre page."
    )
    assert "0,0000" in corps, (
        f"Le montant n'apparaît pas au format de l'écran dans l'export : {corps[:200]}"
    )


def test_the_board_never_loads_its_whole_dataset() -> None:
    """Le cahier l.505 : « aucune liste ne charge intégralement son jeu de
    données ». La première version du kanban faisait exactement l'inverse.

    **Une première version de CE TEST ne mesurait pas la bonne chose**, et
    la falsification F119 l'a dit : elle comparait le NOMBRE DE REQUÊTES
    entre un petit et un grand jeu — or un chargement complet n'en fait
    qu'une seule, quel que soit le volume. Le compte était identique dans
    les deux cas, et la mutation passait.

    Ce qui distingue les deux, c'est la forme du SQL : une lecture bornée
    porte un `LIMIT`, un chargement complet n'en a pas. Le test lit donc le
    SQL réellement envoyé à PostgreSQL."""
    from apps.sales.models import SalesOrder
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    tenant = Tenant.objects.create(code="D0KB", name="Societe tableau")
    user = User.objects.create_user(email="d0-kb@example.com", password="Str0ngPassw0rd!23")
    grant_module_access(user, "sales")
    client = _client(tenant, user)

    for _ in range(6):
        _commande(tenant)

    with CaptureQueriesContext(connection) as requetes:
        reponse = client.get("/sales/orders/?presentation=kanban")

    table = SalesOrder._meta.db_table
    lectures = [
        requete["sql"]
        for requete in requetes
        if f'FROM "{table}"' in requete["sql"] and "COUNT(" not in requete["sql"].upper()
    ]
    assert lectures, (
        "Aucune lecture des commandes n'a été observée : le test ne mesure rien "
        "(l'écran a-t-il rendu le tableau ?)."
    )
    sans_borne = [sql for sql in lectures if "LIMIT" not in sql.upper()]
    assert not sans_borne, (
        "Le tableau lit les commandes SANS BORNE — il charge donc tout le jeu de "
        f"données pour n'en montrer que le plafond par colonne :\n  {sans_borne[0][:300]}"
    )

    contenu = reponse.content.decode()
    assert contenu.count('<article class="card"') <= 5 * 50, (
        "Le tableau rend plus de cartes que son plafond par colonne."
    )
    assert "6" in contenu, "Le total annoncé par la colonne ne compte plus toutes les lignes."


def test_an_empty_list_says_more_than_nothing() -> None:
    """22 des 23 listes des quatre modules tombaient sur une cellule
    « Aucun résultat. » — et 7 d'entre elles ne rendaient littéralement
    rien d'autre pour un rôle en lecture seule. Un tableau vide ne dit ni
    s'il n'y a rien, ni si le filtre est trop étroit, ni quoi faire
    ensuite ; le composant qui le dit existe depuis CRM-5 et n'était posé
    que sur une seule liste."""
    tenant = Tenant.objects.create(code="D0VD", name="Societe vide")
    user = User.objects.create_user(email="d0-vide@example.com", password="Str0ngPassw0rd!23")
    grant_module_access(user, "sales")
    client = _client(tenant, user)

    contenu = client.get("/sales/orders/?presentation=liste").content.decode()
    assert "Aucun résultat." not in contenu, "La cellule muette est toujours là."
    assert "Rien à afficher" in contenu, "L'écran vide ne dit pas ce qu'on doit y attendre."

    filtre = client.get(
        "/sales/orders/", {"presentation": "liste", "q": "introuvable-xyz"}
    ).content.decode()
    assert "Aucun résultat pour cette recherche" in filtre, (
        "Un écran vide PARCE QUE filtré dit la même chose qu'un écran vide parce que "
        "rien n'existe : l'utilisateur ne peut pas distinguer les deux."
    )
