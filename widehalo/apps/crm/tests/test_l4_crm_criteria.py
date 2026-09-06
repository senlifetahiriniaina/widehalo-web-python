"""L4 — les cinq critères CRM, dont quatre étaient ❌ à l'audit.

Ce que chacun cachait, et que ces tests verrouillent :

- **CRM-1** : aucun kanban n'existait dans `apps/crm` ni `templates/crm` —
  le changement d'étape se faisait par un `<select>` depuis la FICHE, pas
  depuis un pipeline. Et le chatter n'était câblé sur aucun objet CRM,
  alors que le critère exige la transition « dans le chatter ET dans le
  journal d'audit » (le second était déjà automatique).
- **CRM-2** : ni encours ni solde comptable n'existaient sur la fiche
  société, et aucun des deux n'avait de gap public — l'encours n'était même
  pas une fonction, il vivait dans le corps de `confirm_order`.
- **CRM-3** : aucune fonction de conversion nulle part.
- **CRM-4** : le seuil N était une constante de module.
- **CRM-5** : aucun composant d'état vide dans tout le dépôt.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.test import Client

from apps.core.models.chatter import ChatterMessage
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.crm.models import CrmLead, CrmPipeline, CrmStage, CrmTeam
from apps.crm.services.leads import convert_lead_to_partner, create_lead_quick
from apps.crm.services.pipeline import move_lead_to_stage

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ngPassw0rd!23"


@pytest.fixture
def crm_setup():
    tenant = Tenant.objects.create(code="L4-CRM", name="CRM L4 SARL")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="l4-crm@example.com", password=PASSWORD)
        # `resp_commercial` et non `direction` : « direction », « admin »,
        # « comptable » et « rh » sont dans `CORE_MFA_REQUIRED_ROLES`, et un
        # utilisateur porteur de l'un d'eux est redirige vers l'enrolement
        # MFA avant d'atteindre le moindre ecran — les reponses reviennent
        # vides et les assertions echouent pour une raison qui n'a rien a
        # voir avec le critere teste. Piege deja rencontre en L17.
        # `resp_commercial` porte crm/partners/sales/accounting en lecture,
        # ce dont ces tests ont besoin, sans MFA.
        Group.objects.get_or_create(name="resp_commercial")[0].user_set.add(user)
        pipeline = CrmPipeline.objects.create(tenant=tenant, name="Ventes", is_default=True)
        first = CrmStage.objects.create(
            tenant=tenant, pipeline=pipeline, code="nouveau", name="Nouveau", sequence=1
        )
        second = CrmStage.objects.create(
            tenant=tenant, pipeline=pipeline, code="qualifie", name="Qualifie", sequence=2
        )
        # `resp_commercial` est scope PAR EQUIPE (`scope_leads_for_user`) :
        # une piste sans equipe lui est invisible, et c'est correct. Le
        # premier jet de ce fichier l'ignorait et le test du kanban
        # echouait — le perimetre faisait exactement son travail.
        team = CrmTeam.objects.create(tenant=tenant, name="Equipe L4", leader=user)
    return tenant, user, pipeline, first, second, team


def _client(tenant: Tenant, user: User) -> Client:
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


# --- CRM-1 : kanban et chatter -------------------------------------------------


def test_the_pipeline_kanban_exists_and_shows_one_column_per_stage(crm_setup) -> None:
    tenant, user, _pipeline, first, second, team = crm_setup
    with use_tenant(tenant.id):
        create_lead_quick(tenant=tenant, name="Affaire A", salesperson=user, team=team)
    client = _client(tenant, user)

    body = client.get("/crm/kanban/").content.decode()
    assert first.name in body
    assert second.name in body
    assert "Affaire A" in body


def test_moving_a_lead_writes_the_transition_to_the_chatter(crm_setup) -> None:
    """Le critere exige la transition « dans le chatter ET dans le journal
    d'audit ». Le journal etait deja automatique ; le chatter n'etait cable
    sur AUCUN objet CRM."""
    tenant, user, _pipeline, _first, second, team = crm_setup
    with use_tenant(tenant.id):
        lead = create_lead_quick(tenant=tenant, name="Affaire B", salesperson=user)
        move_lead_to_stage(lead, second, moved_by=user)

        messages = ChatterMessage.objects.filter(object_id=str(lead.id))
        assert messages.count() == 1
        assert second.name in messages.first().body


def test_a_transition_without_an_author_still_moves_the_lead(crm_setup) -> None:
    """La falsification : `moved_by` est optionnel, et son absence ne doit
    jamais empecher la transition — un flux automatise n'a pas d'auteur
    humain, et `ChatterMessage.author` n'accepte pas `None`."""
    tenant, user, _pipeline, _first, second, team = crm_setup
    with use_tenant(tenant.id):
        lead = create_lead_quick(tenant=tenant, name="Affaire C", salesperson=user)
        move_lead_to_stage(lead, second)

        lead.refresh_from_db()
        assert lead.stage_id == second.id
        assert not ChatterMessage.objects.filter(object_id=str(lead.id)).exists()


def test_the_chatter_thread_of_a_colleagues_lead_is_refused(crm_setup) -> None:
    """La garde de perimetre du chatter.

    Sans `services.chatter_registration`, le repli de
    `core.views.chatter._can_view_chatter_object` est la permission de
    MODELE `crm.view_crmlead`, que tout commercial porte : le fil de
    discussion de l'opportunite d'un collegue — notes internes, motifs de
    perte — serait lisible et ecrivable par simple connaissance de l'UUID.
    C'est la faille des bloquants (4/4), sur une autre surface."""
    tenant, _user, _pipeline, _first, _second, _team = crm_setup
    with use_tenant(tenant.id):
        mine = User.objects.create_user(email="l4-mine@example.com", password=PASSWORD)
        theirs = User.objects.create_user(email="l4-theirs@example.com", password=PASSWORD)
        commercial = Group.objects.get_or_create(name="commercial")[0]
        commercial.user_set.add(mine, theirs)
        their_lead = create_lead_quick(tenant=tenant, name="Chasse gardee", salesperson=theirs)
        my_lead = create_lead_quick(tenant=tenant, name="La mienne", salesperson=mine)

    client = _client(tenant, mine)
    refused = client.get(f"/chatter/crm/crmlead/{their_lead.id}/")
    assert refused.status_code == 403

    # La falsification : mon propre fil reste accessible. Sans elle, « la
    # garde protege » et « la garde bloque tout le monde » seraient
    # indiscernables.
    allowed = client.get(f"/chatter/crm/crmlead/{my_lead.id}/")
    assert allowed.status_code == 200


# --- CRM-2 : encours, solde, trois derniers documents --------------------------


def test_the_partner_sheet_shows_outstanding_balance_and_three_documents(crm_setup) -> None:
    """« Sans navigation supplementaire » : les trois informations sont
    dans le corps de la page, hors de tout onglet a cliquer."""
    import datetime as dt

    from apps.partners.services.public import ROLE_CLIENT, create_partner_with_contact_from_source
    from apps.sales.services.orders import add_order_line, create_order

    tenant, user, _pipeline, _first, _second, team = crm_setup
    with use_tenant(tenant.id):
        created = create_partner_with_contact_from_source(
            tenant, name="Client L4", role=ROLE_CLIENT
        )
        partner_id = created["partner_id"]
        for index in range(4):
            order = create_order(tenant=tenant, partner_id=partner_id, date=dt.date.today())
            add_order_line(
                order,
                description=f"Ligne {index}",
                qty=Decimal("1"),
                unit_price=Decimal("1000"),
                is_custom=True,
            )

    client = _client(tenant, user)
    body = client.get(f"/partners/{partner_id}/").content.decode()

    assert "Encours commercial" in body
    assert "Solde comptable" in body
    # Trois derniers, pas quatre.
    assert body.count("Commande CMD-") == 3


def test_outstanding_is_the_same_definition_the_credit_check_uses(crm_setup) -> None:
    """L'encours affiche doit etre CELUI de RG-SAL-4, pas un second calcul.

    Une regle de calcul recopiee est une regle qui divergera : la fiche
    montrerait un encours, le controle de credit en appliquerait un autre.
    """
    import datetime as dt

    from apps.partners.services.public import ROLE_CLIENT, create_partner_with_contact_from_source
    from apps.sales.services.orders import (
        ENGAGED_STATES,
        add_order_line,
        confirm_order,
        create_order,
        outstanding_amount_for_partner,
    )
    from apps.sales.services.public import get_outstanding_amount_for_partner

    tenant, user, _pipeline, _first, _second, team = crm_setup
    with use_tenant(tenant.id):
        created = create_partner_with_contact_from_source(
            tenant, name="Client encours", role=ROLE_CLIENT
        )
        partner_id = created["partner_id"]
        order = create_order(tenant=tenant, partner_id=partner_id, date=dt.date.today())
        add_order_line(
            order,
            description="Ligne",
            qty=Decimal("2"),
            unit_price=Decimal("5000"),
            is_custom=True,
        )
        # Un devis non confirme ne compte pas : l'encours ne porte que les
        # commandes ENGAGEES.
        assert get_outstanding_amount_for_partner(tenant, partner_id) == Decimal(0)

        confirm_order(order, user)
        order.refresh_from_db()
        assert order.state in ENGAGED_STATES
        assert get_outstanding_amount_for_partner(tenant, partner_id) == order.amount_total_mga
        assert outstanding_amount_for_partner(tenant, partner_id) == order.amount_total_mga


# --- CRM-3 : conversion --------------------------------------------------------


def test_converting_a_lead_creates_the_company_and_its_contact_without_retyping(
    crm_setup,
) -> None:
    """« Sans ressaisie d'aucun champ deja renseigne » : la piste porte
    deja nom, contact, e-mail et telephone — il n'y avait qu'a les
    transmettre."""
    from apps.partners.services.public import get_partner_display_name

    tenant, user, _pipeline, _first, _second, team = crm_setup
    with use_tenant(tenant.id):
        lead = create_lead_quick(
            tenant=tenant,
            name="Imprimerie du Sud",
            salesperson=user,
            contact_name="Rakoto Jean",
            email="rakoto@example.com",
            phone="+261340000001",
        )
        assert lead.partner_id is None

        convert_lead_to_partner(lead)
        lead.refresh_from_db()

        assert lead.partner_id is not None
        assert get_partner_display_name(lead.partner_id) == "Imprimerie du Sud"

        from apps.partners.models import PartnerContact

        contact = PartnerContact.objects.get(partner_id=lead.partner_id)
        assert contact.full_name == "Rakoto Jean"
        assert contact.email == "rakoto@example.com"
        assert contact.is_primary


def test_converting_twice_does_not_create_a_second_company(crm_setup) -> None:
    """Idempotente : un double clic sur un parcours sans danger ne doit pas
    fabriquer un doublon de societe."""
    from apps.partners.models import Partner

    tenant, user, _pipeline, _first, _second, team = crm_setup
    with use_tenant(tenant.id):
        lead = create_lead_quick(tenant=tenant, name="Deux fois", salesperson=user)
        convert_lead_to_partner(lead)
        first_partner_id = lead.partner_id
        convert_lead_to_partner(lead)

        assert lead.partner_id == first_partner_id
        assert Partner.objects.filter(tenant=tenant, name="Deux fois").count() == 1


# --- CRM-4 : seuil paramétrable et tuile ---------------------------------------


def test_the_follow_up_threshold_is_read_from_the_pipeline(crm_setup) -> None:
    """N n'est plus une constante : deux pipelines de seuils differents
    classent differemment la MEME anciennete."""
    import datetime as dt

    from django.utils import timezone

    from apps.crm.services.stagnation import stagnant_leads

    tenant, user, pipeline, _first, _second, team = crm_setup
    with use_tenant(tenant.id):
        lead = create_lead_quick(tenant=tenant, name="Dormante", salesperson=user)
        CrmLead.objects.filter(pk=lead.pk).update(created_at=timezone.now() - dt.timedelta(days=30))

        # Seuil par defaut (21 j) : l'opportunite est en retard.
        assert [row[0].id for row in stagnant_leads(str(tenant.id))] == [lead.id]

        # Seuil releve a 60 j : la MEME opportunite ne l'est plus.
        pipeline.stagnant_after_days = 60
        pipeline.save(update_fields=["stagnant_after_days"])
        assert stagnant_leads(str(tenant.id)) == []


def test_the_launchpad_shows_the_overdue_follow_up_tile(crm_setup) -> None:
    import datetime as dt

    from django.utils import timezone

    tenant, user, _pipeline, _first, _second, team = crm_setup
    with use_tenant(tenant.id):
        lead = create_lead_quick(tenant=tenant, name="Oubliee", salesperson=user)
        CrmLead.objects.filter(pk=lead.pk).update(created_at=timezone.now() - dt.timedelta(days=40))

    client = _client(tenant, user)
    session = client.session
    session["use_new_shell"] = True
    session.save()
    body = client.get("/launchpad/").content.decode()
    assert "Relances en retard" in body


def test_the_threshold_can_be_changed_from_the_configuration_screen(crm_setup) -> None:
    """« N PARAMETRABLE » : le champ doit etre atteignable, pas seulement
    exister en base."""
    tenant, user, pipeline, _first, _second, team = crm_setup
    client = _client(tenant, user)

    response = client.post(
        f"/crm/config/pipelines/{pipeline.id}/",
        {"action": "set_stagnation", "stagnant_after_days": "45"},
    )
    assert response.status_code == 200

    pipeline.refresh_from_db()
    assert pipeline.stagnant_after_days == 45


# --- CRM-5 : état vide ---------------------------------------------------------


def test_an_empty_pipeline_shows_a_teaching_empty_state(crm_setup) -> None:
    tenant, user, _pipeline, _first, _second, team = crm_setup
    client = _client(tenant, user)

    body = client.get("/crm/").content.decode()
    assert "Aucune opportunité pour l" in body
    assert "Nouvelle opportunité" in body
    # Le tableau vide n'est PAS rendu a sa place.
    assert "Aucun résultat." not in body


def test_a_search_that_matches_nothing_keeps_the_table(crm_setup) -> None:
    """La falsification, et elle a un sens metier : « je n'ai rien » et
    « mon filtre est trop fin » n'appellent pas la meme reponse. Un etat
    vide qui remplacerait aussi le second cacherait la barre de recherche a
    qui veut la corriger."""
    tenant, user, _pipeline, _first, _second, team = crm_setup
    with use_tenant(tenant.id):
        create_lead_quick(tenant=tenant, name="Existante", salesperson=user, team=team)
    client = _client(tenant, user)

    body = client.get("/crm/?q=inexistant-xyz").content.decode()
    assert "Aucune opportunité pour l" not in body
