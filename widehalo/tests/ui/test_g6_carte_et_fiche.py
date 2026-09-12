"""G-6 — la carte de kanban, et sa fiche en popup.

**La conception vient du commanditaire**, et elle tranche un conflit du
cahier : la maquette demande quatre champs sur la carte — client, montant,
date de clôture, prochaine activité — et le même cahier demande par
ailleurs une « vue à densité réduite ». Quatre champs sur une carte de
15 rem produisent une bouillie. Deux à trois lignes déclarées par le
module, et tout le reste dans une fiche ouverte au clic, tiennent les deux.

« Une fichier modifiable ou non selon le rôle de l'utilisateur en cours » :
un lecteur voit la fiche et aucune action ; un rédacteur voit les suites
que C-3 calcule pour lui. Jamais un formulaire affiché puis refusé à
l'envoi — le défaut corrigé en C-1d.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.services.presentation import (
    Board,
    LigneResume,
    register_board,
)
from apps.core.tests.utils import grant_module_access, grant_role, use_tenant
from apps.partners.models import Partner
from apps.sales.models import SalesOrder
from apps.sales.services.orders import add_order_line, create_order
from django.test import Client

pytestmark = pytest.mark.django_db


def _connecte(user: User, tenant: Tenant) -> Client:
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


@pytest.fixture
def societe():
    tenant = Tenant.objects.create(code="G6", name="Societe kanban")
    user = User.objects.create_user(email="g6@example.com", password="Str0ngPassw0rd!23")
    grant_module_access(user, "sales")
    UserTenantMembership.objects.get_or_create(
        user=user, tenant=tenant, defaults={"is_default": True}
    )
    with use_tenant(tenant.id):
        client_tiers = Partner.objects.create(
            tenant=tenant, name="Cliente Rasoa", nif="1234567890", roles=[Partner.ROLE_CLIENT]
        )
        commande = create_order(tenant=tenant, partner_id=client_tiers.id, date=dt.date(2026, 4, 1))
        add_order_line(
            commande,
            description="Tissu coton",
            qty=Decimal("10"),
            unit_price=Decimal("15000"),
            is_custom=True,
        )
        commande.refresh_from_db()
    return {
        "tenant": tenant,
        "user": user,
        "client": _connecte(user, tenant),
        "client_tiers": client_tiers,
        "commande": commande,
    }


def test_la_carte_porte_le_resume_declare_et_pas_un_identifiant(societe) -> None:
    """La carte dit le client et le montant — c'est ce que le module
    déclare, et le nom vient du crochet d'enrichissement que C-4 excluait
    du kanban tant que la carte ne rendait que son titre."""
    contenu = societe["client"].get("/sales/orders/?presentation=kanban").content.decode()
    assert "Cliente Rasoa" in contenu, "La carte ne nomme pas le client."
    assert str(societe["client_tiers"].id) not in contenu, (
        "La carte rend l'identifiant technique du tiers."
    )
    assert "150 000 Ar" in contenu, "La carte ne porte pas le montant formaté."


def test_la_carte_ouvre_la_fiche_du_document(societe) -> None:
    commande = societe["commande"]
    contenu = societe["client"].get("/sales/orders/?presentation=kanban").content.decode()
    chemin = f"/documents/card/sales.SalesOrder/{commande.id}/"
    assert chemin in contenu, "La carte ne charge aucune fiche au clic."
    assert 'role="dialog"' in contenu, "Le tableau n'a pas de popup pour recevoir la fiche."

    fiche = societe["client"].get(chemin)
    assert fiche.status_code == 200
    corps = fiche.content.decode()
    assert "Cliente Rasoa" in corps
    assert commande.reference in corps
    # La fiche porte PLUS que la carte : c'est sa raison d'être.
    assert "Commercial" in corps
    assert "Statut" in corps


def test_la_fiche_est_modifiable_pour_qui_peut_ecrire(societe) -> None:
    commande = societe["commande"]
    corps = (
        societe["client"].get(f"/documents/card/sales.SalesOrder/{commande.id}/").content.decode()
    )
    assert "lecture seule" not in corps
    # Une commande en brouillon a au moins une suite : la confirmer.
    assert "Étape suivante" in corps


def test_la_fiche_est_en_lecture_seule_pour_qui_ne_peut_pas_ecrire(societe) -> None:
    """« Modifiable ou non selon le rôle de l'utilisateur en cours » —
    `controleur_gestion` a `view` sur `sales` et rien d'autre."""
    tenant = societe["tenant"]
    lecteur = User.objects.create_user(email="g6-lecture@example.com", password="Str0ngPassw0rd!23")
    grant_role(lecteur, "controleur_gestion")
    UserTenantMembership.objects.get_or_create(
        user=lecteur, tenant=tenant, defaults={"is_default": True}
    )
    reponse = _connecte(lecteur, tenant).get(
        f"/documents/card/sales.SalesOrder/{societe['commande'].id}/"
    )
    assert reponse.status_code == 200
    corps = reponse.content.decode()
    assert "lecture seule" in corps, "La fiche ne dit pas qu'elle est en lecture seule."
    assert "Étape suivante" not in corps, "La fiche propose une action qu'elle refusera."
    # La fiche reste LISIBLE : un rôle en lecture doit voir le contenu.
    assert societe["commande"].reference in corps


def test_un_role_sans_droit_de_lecture_est_refuse(societe) -> None:
    tenant = societe["tenant"]
    caissier = User.objects.create_user(email="g6-caisse@example.com", password="Str0ngPassw0rd!23")
    grant_role(caissier, "caissier")
    UserTenantMembership.objects.get_or_create(
        user=caissier, tenant=tenant, defaults={"is_default": True}
    )
    reponse = _connecte(caissier, tenant).get(
        f"/documents/card/sales.SalesOrder/{societe['commande'].id}/"
    )
    assert reponse.status_code == 403


def test_un_modele_sans_tableau_declare_na_pas_de_fiche(societe) -> None:
    """La route ne doit pas ouvrir une fiche sur n'importe quel modèle du
    produit : certains portent des champs que le §9.2 exclut de toute
    sortie."""
    reponse = societe["client"].get(
        f"/documents/card/partners.Partner/{societe['client_tiers'].id}/"
    )
    assert reponse.status_code == 404


def test_un_type_de_document_inconnu_rend_404_jamais_500(societe) -> None:
    reponse = societe["client"].get(f"/documents/card/pas.UnModele/{societe['commande'].id}/")
    assert reponse.status_code == 404


def test_un_resume_hors_bornes_est_refuse_a_la_declaration() -> None:
    """La garde de `register_board` mord : une carte à une ligne ne dit rien
    de plus que son titre, et quatre lignes contredisent la densité réduite
    que le cahier demande."""
    une_ligne = (LigneResume(label="Montant", attribut="amount_total_mga"),)
    fiche = (LigneResume(label="Référence", attribut="reference"),)
    with pytest.raises(ValueError, match="ligne"):
        register_board(
            "tests.TropCourt",
            Board(state_field="state", par_etat={}, resume=une_ligne, fiche=fiche),
        )
    with pytest.raises(ValueError, match="fiche"):
        register_board(
            "tests.SansFiche",
            Board(
                state_field="state",
                par_etat={},
                resume=une_ligne + une_ligne,
                fiche=(),
            ),
        )


def test_la_liste_et_la_carte_disent_le_meme_statut(societe) -> None:
    """Un écran qui se contredirait serait pire que pas de kanban."""
    kanban = societe["client"].get("/sales/orders/?presentation=kanban").content.decode()
    liste = societe["client"].get("/sales/orders/?presentation=liste").content.decode()
    libelle = SalesOrder(state=societe["commande"].state).get_state_display()
    assert libelle in kanban
    assert libelle in liste


# --------------------------------------------------------------------------
# Le pipeline du CRM : sa carte, et ses deux totaux par colonne
# --------------------------------------------------------------------------
#
# Le CRM ne passe pas par le registre de projection — ses colonnes SONT ses
# `CrmStage`, un pipeline configurable par société que CRM-4 a livré. Sa
# carte est donc traitée séparément, et la 0.1.8 mesurait ce qui lui
# manquait : « ni client, ni date de clôture prévue, ni prochaine activité ;
# aucun total pondéré ».


@pytest.fixture
def pipeline():
    from apps.crm.models import CrmActivity, CrmPipeline, CrmStage
    from apps.crm.services.leads import create_lead_quick

    tenant = Tenant.objects.create(code="G6C", name="Societe pipeline")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="g6-crm@example.com", password="Str0ngPassw0rd!23")
        grant_role(user, "commercial")
        UserTenantMembership.objects.get_or_create(
            user=user, tenant=tenant, defaults={"is_default": True}
        )
        tuyau = CrmPipeline.objects.create(tenant=tenant, name="Standard", is_default=True)
        CrmStage.objects.create(
            tenant=tenant, pipeline=tuyau, code="new", name="Nouveau", sequence=1
        )
        CrmStage.objects.create(
            tenant=tenant, pipeline=tuyau, code="qualified", name="Qualifié", sequence=2
        )
        tiers = Partner.objects.create(
            tenant=tenant, name="Cliente Rasoa", nif="1234567890", roles=[Partner.ROLE_CLIENT]
        )
        opportunite = create_lead_quick(tenant=tenant, name="Marché textile", salesperson=user)
        opportunite.partner_id = tiers.id
        opportunite.expected_revenue_mga = Decimal("4000000")
        opportunite.probability = 25
        opportunite.expected_close_date = dt.date(2026, 12, 31)
        opportunite.save(
            update_fields=[
                "partner_id",
                "expected_revenue_mga",
                "probability",
                "expected_close_date",
            ]
        )
        CrmActivity.objects.create(
            tenant=tenant,
            lead=opportunite,
            activity_type=CrmActivity.TYPE_CALL,
            subject="Rappeler la cliente",
            due_at=dt.datetime(2026, 5, 12, 9, 0, tzinfo=dt.UTC),
        )
    return {"tenant": tenant, "client": _connecte(user, tenant), "opportunite": opportunite}


def test_la_carte_du_pipeline_porte_les_quatre_champs_de_la_maquette(pipeline) -> None:
    contenu = pipeline["client"].get("/crm/kanban/").content.decode()
    assert "Cliente Rasoa" in contenu, "La carte ne nomme pas le client."
    assert "4 000 000 Ar" in contenu, "La carte ne porte pas le montant attendu."
    assert "Clôture prévue" in contenu, "La carte ne dit pas la date de clôture prévue."
    assert "Appel" in contenu, "La carte ne dit pas la prochaine activité."


def test_chaque_colonne_du_pipeline_annonce_son_total_brut_et_pondere(pipeline) -> None:
    """Le total pondéré que le cahier demande, et l'écart qui est
    l'information : 4 000 000 attendus à 25 % valent 1 000 000 espérés."""
    contenu = pipeline["client"].get("/crm/kanban/").content.decode()
    assert "4 000 000 Ar" in contenu
    assert "1 000 000 Ar" in contenu, "Le total pondéré de la colonne n'apparaît pas."
    assert "pondéré" in contenu
