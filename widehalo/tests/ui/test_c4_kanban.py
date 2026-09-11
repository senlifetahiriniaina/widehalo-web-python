"""C-4 (2/2) — le kanban, la bascule, et l'accord entre les deux vues.

Quatre propriétés, chacune vérifiée sur ce qui ARRIVE AU NAVIGATEUR :

1. **Le défaut suit le processus.** Un document qui déclare une
   projection s'ouvre en kanban ; celui qui n'en déclare pas reste en
   liste. C'est la « liaison entre la liste/kanban et le processus »
   demandée par le commanditaire.
2. **La bascule surcharge, et le choix survit.** Sans mémorisation, un
   utilisateur qui préfère la liste la redemanderait à chaque visite.
3. **Les deux vues s'accordent.** Une ligne rangée dans « Bloqué » au
   tableau doit porter le même statut en liste : c'est la même
   projection, et un écran qui se contredirait serait pire que pas de
   kanban du tout.
4. **La troncature se dit.** C-2 a trouvé un écran qui montrait « les 50
   plus récentes » sans le signaler ; le kanban plafonne aussi, mais
   l'annonce.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.ui import ScreenPreference
from apps.core.models.user import User, UserTenantMembership
from apps.core.services.presentation import column_of
from apps.core.tests.utils import grant_module_access, use_tenant
from apps.sales.models import SalesOrder
from apps.sales.services.orders import create_order
from django.test import Client

pytestmark = pytest.mark.django_db


def _client_et_societe() -> tuple[Client, Tenant, User]:
    tenant = Tenant.objects.create(code="C4K", name="Societe kanban")
    user = User.objects.create_user(email="c4k@example.com", password="Str0ngPassw0rd!23")
    grant_module_access(user, "sales", "accounting", "logistics")
    UserTenantMembership.objects.get_or_create(
        user=user, tenant=tenant, defaults={"is_default": True}
    )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, user


def test_a_document_with_a_process_opens_as_a_board() -> None:
    """`SalesOrder` déclare une projection : sa liste s'ouvre en kanban."""
    client, tenant, _user = _client_et_societe()
    with use_tenant(tenant.id):
        create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())

    contenu = client.get("/sales/orders/").content.decode()
    assert "En attente" in contenu and "Bloqu" in contenu, (
        "La liste des commandes ne s'ouvre pas en kanban alors que le document "
        "déclare une projection : le défaut ne suit pas le processus."
    )


def test_the_toggle_overrides_and_the_choice_survives() -> None:
    client, tenant, user = _client_et_societe()
    with use_tenant(tenant.id):
        create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())

    client.get("/sales/orders/", {"presentation": "liste"})
    # `objects` est un `TenantManager` : hors contexte de société il ne rend
    # rien, et l'assertion échouerait pour une raison étrangère à ce qu'elle
    # teste. Piège déjà payé en T9 sur les assertions de purge.
    with use_tenant(tenant.id):
        enregistree = ScreenPreference.objects.filter(owner=user, presentation="liste").exists()
    assert enregistree, "La bascule n'a rien enregistré : le choix ne survivra pas à la visite."

    # Visite suivante, SANS paramètre : la liste doit revenir.
    contenu = client.get("/sales/orders/").content.decode()
    assert "smart-table-export-links" in contenu, (
        "Le choix « liste » n'a pas été honoré à la visite suivante."
    )


def test_a_row_lands_in_the_column_its_projection_names() -> None:
    """La propriété qui fait tenir tout le lot, vérifiée À L'ÉCRAN.

    La version précédente de ce test comparait deux appels de `column_of`
    entre eux : elle aurait passé même si le gabarit rangeait toutes les
    cartes dans la première colonne. Ce qui doit être vrai, c'est que la
    carte se trouve DANS la section que la projection nomme — et dans
    aucune autre.

    Que la cellule de liste et la carte disent le même mot est vérifié par
    `test_c4_listes_lisibles.py`, sur les deux rendus."""
    client, tenant, _user = _client_et_societe()
    with use_tenant(tenant.id):
        attendue = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        sans_suite = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        sans_suite.state = SalesOrder.STATE_CANCELLED
        sans_suite.save(update_fields=["state"])

    assert column_of(attendue) == "en_attente" and column_of(sans_suite) == "sans_suite", (
        "Le jeu d'essai ne couvre plus deux colonnes distinctes."
    )

    contenu = client.get("/sales/orders/?presentation=kanban").content.decode()
    sections = re.findall(r"<section class=\"panel\".*?</section>", contenu, re.S)
    assert len(sections) == 5, f"Le tableau ne rend pas ses cinq colonnes ({len(sections)})."

    # **Deux lignes de colonnes DIFFERENTES, et c'est une leçon payée.** La
    # première version de ce test n'avait qu'une commande en brouillon,
    # c'est-à-dire dans la PREMIERE colonne : la falsification F104, qui
    # jetait toutes les cartes dans la première colonne, ne l'a pas fait
    # tomber. Un test qui passe pour la mauvaise raison est pire qu'aucun.
    for commande, libelle in ((attendue, "En attente"), (sans_suite, "Sans suite")):
        portant = [section for section in sections if commande.reference in section]
        assert len(portant) == 1, (
            f"La commande {commande.reference} apparaît dans {len(portant)} colonnes au lieu d'une."
        )
        assert libelle in portant[0], (
            f"La commande {commande.reference} n'est pas dans la colonne « {libelle} » que sa "
            "projection lui donne."
        )


def test_a_document_without_a_process_stays_a_list() -> None:
    """Un référentiel n'a pas de processus : pas de kanban, et pas de
    bascule non plus — proposer un tableau que l'écran ne sait pas rendre
    serait la faute que C-1d a corrigée sur les boutons."""
    client, _tenant, _user = _client_et_societe()
    contenu = client.get("/logistics/config/hs-codes/").content.decode()
    assert "?presentation=kanban" not in contenu, (
        "Un référentiel propose une bascule kanban qu'il ne saurait pas honorer."
    )
    assert "smart-table-export-links" in contenu, "Le référentiel ne rend plus sa liste."
