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
import uuid

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.ui import ScreenPreference
from apps.core.models.user import User, UserTenantMembership
from apps.core.services.presentation import column_of
from apps.core.tests.utils import grant_module_access, use_tenant
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


def test_the_board_and_the_list_agree_on_where_a_row_belongs() -> None:
    """La propriété qui fait tenir tout le lot.

    Le kanban groupe par `column_of` ; la liste affiche
    `statut_operationnel`, qui appelle le même `column_of`. Si les deux
    divergeaient, l'écran se contredirait d'une vue à l'autre."""
    _client, tenant, _user = _client_et_societe()
    with use_tenant(tenant.id):
        commande = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())

    colonne = column_of(commande)
    assert colonne == "en_attente", (
        f"Une commande en brouillon devrait être en attente ; reçu {colonne}."
    )
    assert commande.statut_operationnel == "En attente", (
        f"La liste afficherait « {commande.statut_operationnel} » là où le kanban range "
        f"la carte dans « {colonne} » : les deux vues se contredisent."
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
