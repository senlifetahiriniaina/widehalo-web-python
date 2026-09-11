"""C-4 — « la suite à prendre » arrive vraiment à l'écran.

C-3 calcule les suites ; ce test verifie qu'elles se rendent. La
distinction n'est pas theorique : un socle correct et un gabarit qui ne
l'inclut pas donnent un ecran identique a celui d'avant, et les tests du
socle passent tous. C'est le motif « rien de decoratif » applique a la
presentation.

Trois proprietes, chacune verifiee sur ce qui ARRIVE AU NAVIGATEUR :

1. Un utilisateur qui peut ecrire voit la suite, avec son libelle lisible.
2. Un utilisateur en LECTURE SEULE ne voit aucune suite — pas des boutons
   grises : la liste est vide, et l'ecran le dit.
3. Ce que le bouton poste est ce que la vue attend. Un bandeau qui
   afficherait la bonne etape et posterait la mauvaise valeur serait pire
   qu'aucun bandeau.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.services.next_steps import next_steps_for
from apps.core.tests.utils import grant_module_access, use_tenant
from apps.sales.services.orders import create_order
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


def _commande() -> tuple[Tenant, object]:
    tenant = Tenant.objects.create(code="C4", name="Societe C-4")
    with use_tenant(tenant.id):
        commande = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
    return tenant, commande


def test_the_next_step_is_shown_to_someone_who_can_act() -> None:
    tenant, commande = _commande()
    dote = User.objects.create_user(email="c4-dote@example.com", password="Str0ngPassw0rd!23")
    grant_module_access(dote, "sales")
    contenu = _client(tenant, dote).get(f"/sales/orders/{commande.id}/").content.decode()

    assert "Étape suivante" in contenu or "&#xC9;tape suivante" in contenu, (
        "La fiche commande n'affiche pas le bandeau de prochaine action."
    )
    assert "Envoyer au client" in contenu, (
        "Le bandeau n'annonce pas la suite attendue pour une commande en brouillon."
    )


def test_a_read_only_user_is_offered_nothing_rather_than_greyed_buttons() -> None:
    """`controleur_gestion` a `view` sur `sales` et rien de plus.

    L'ecran doit le DIRE — « aucune étape suivante » — plutot que de
    montrer des boutons qu'il refusera : c'est la regle posee en C-1d."""
    tenant, commande = _commande()
    from apps.core.tests.utils import grant_role

    lecteur = User.objects.create_user(email="c4-lecteur@example.com", password="Str0ngPassw0rd!23")
    grant_role(lecteur, "controleur_gestion")
    contenu = _client(tenant, lecteur).get(f"/sales/orders/{commande.id}/").content.decode()

    assert "Aucune étape suivante" in contenu or "Aucune &#xE9;tape suivante" in contenu, (
        "Un role en lecture seule ne voit pas le message d'absence de suite."
    )
    assert "Envoyer au client" not in contenu, (
        "Un role en lecture seule se voit proposer une action que la garde refusera."
    )


def test_what_the_banner_posts_is_what_the_view_expects() -> None:
    """Ce que le bandeau poste REELLEMENT, lu sur le bandeau.

    **Ce test trichait, et il faut le dire.** Sa premiere version postait
    `{"action": "send"}` — une valeur ecrite en dur ici. Elle verifiait donc
    que la VUE sait traiter « send », jamais que le BANDEAU poste ce que la
    vue attend. Elle est restee verte pendant que dix boutons des six fiches
    ne faisaient rien : la fiche CRM postait un UUID d'etape, la commande
    postait `mark_invoiced` la ou la vue attend `invoice`, et la facture
    proposait cinq transitions sans branche.

    La valeur postee vient maintenant du registre, jamais du test. Le
    parcours complet — toutes les etapes, a tous les etats du cycle de vie
    — vit dans `tests/ui/test_da_boutons_agissent.py` ; celui-ci garde la
    propriete sur l'etat initial d'une commande, la ou le lot C-4 l'avait
    posee."""
    tenant, commande = _commande()
    dote = User.objects.create_user(email="c4-poste@example.com", password="Str0ngPassw0rd!23")
    grant_module_access(dote, "sales")
    client = _client(tenant, dote)

    with use_tenant(tenant.id):
        etapes = next_steps_for(commande, dote)
    assert etapes, "Aucune etape proposee : le test ne mesure plus rien."

    avant = commande.state
    reponse = client.post(f"/sales/orders/{commande.id}/", etapes[0].champs())
    assert reponse.status_code == 302, reponse.content[:400]

    commande.refresh_from_db()
    assert commande.state != avant, (
        f"Le POST du bandeau n'a rien change : l'etat est reste « {avant} ». Ce que le "
        f"bandeau propose — {etapes[0].champs()} — n'est pas ce que la vue sait traiter."
    )
