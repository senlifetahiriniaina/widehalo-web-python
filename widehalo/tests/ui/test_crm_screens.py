from __future__ import annotations

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.crm.models import CrmPipeline, CrmStage
from apps.crm.services.leads import create_lead_quick
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def crm_screens_setup():
    tenant = Tenant.objects.create(code="UI-CRM", name="UI CRM Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="ui-crm@example.com", password="Str0ngPassw0rd!23")
        pipeline = CrmPipeline.objects.create(tenant=tenant, name="Standard", is_default=True)
        stage_new = CrmStage.objects.create(
            tenant=tenant, pipeline=pipeline, code="new", name="Nouveau", sequence=1
        )
        CrmStage.objects.create(
            tenant=tenant, pipeline=pipeline, code="qualified", name="Qualifie", sequence=2
        )
        lead = create_lead_quick(tenant=tenant, name="Opportunite textile", salesperson=user)
        assert lead.stage_id == stage_new.id
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, lead


def test_lead_create_screen(crm_screens_setup) -> None:
    client, _tenant, _lead = crm_screens_setup
    response = client.post("/crm/new/", {"name": "Nouvelle opportunite"})
    assert response.status_code == 302


def test_lead_create_screen_renders_enriched_form_with_partner_picker(crm_screens_setup) -> None:
    client, _tenant, _lead = crm_screens_setup
    response = client.get("/crm/new/")
    assert response.status_code == 200
    assert b'name="pipeline"' in response.content
    assert b'name="team"' in response.content
    assert b'name="priority"' in response.content
    assert b'name="source"' in response.content
    assert b'name="contact_name"' in response.content
    assert b'name="email"' in response.content
    assert b'name="phone"' in response.content
    assert b'name="expected_revenue_mga"' in response.content
    assert b'name="expected_close_date"' in response.content
    assert b'name="description"' in response.content
    # Composant reutilisable UXR3, embarque tel quel (champ cache partner_id).
    assert b'id="partner_id"' in response.content
    assert b"wh-partner-picker" in response.content


def test_lead_create_screen_persists_all_enriched_fields(crm_screens_setup) -> None:
    from apps.core.tests.utils import use_tenant
    from apps.crm.models import CrmLead, CrmPipeline, CrmTeam
    from apps.partners.models import Partner

    client, tenant, _lead = crm_screens_setup
    with use_tenant(tenant.id):
        partner = Partner.objects.create(tenant=tenant, name="Client Textile SARL")
        pipeline = CrmPipeline.objects.create(tenant=tenant, name="Grands comptes")
        stage = pipeline.stages.model.objects.create(
            tenant=tenant, pipeline=pipeline, code="new", name="Nouveau", sequence=1
        )
        team = CrmTeam.objects.create(tenant=tenant, name="Equipe Nord")

    response = client.post(
        "/crm/new/",
        {
            "name": "Opportunite enrichie",
            "partner_id": str(partner.id),
            "pipeline": str(pipeline.id),
            "team": str(team.id),
            "expected_revenue_mga": "1250000.5",
            "expected_close_date": "2026-12-31",
            "priority": "high",
            "source": "salon-professionnel",
            "contact_name": "Rako Andry",
            "email": "rako@example.com",
            "phone": "+261341234567",
            "description": "Grosse commande d'uniformes.",
        },
    )
    assert response.status_code == 302

    with use_tenant(tenant.id):
        lead = CrmLead.objects.get(name="Opportunite enrichie")
        assert lead.partner_id == partner.id
        assert lead.pipeline_id == pipeline.id
        assert lead.stage_id == stage.id
        assert lead.team_id == team.id
        assert str(lead.expected_revenue_mga) == "1250000.5000"
        assert lead.expected_close_date.isoformat() == "2026-12-31"
        assert lead.priority == "high"
        assert lead.source == "salon-professionnel"
        assert lead.contact_name == "Rako Andry"
        assert lead.email == "rako@example.com"
        assert lead.phone == "+261341234567"
        assert lead.description == "Grosse commande d'uniformes."


def test_lead_create_screen_still_works_with_only_name(crm_screens_setup) -> None:
    from apps.core.tests.utils import use_tenant
    from apps.crm.models import CrmLead

    client, tenant, _lead = crm_screens_setup
    response = client.post("/crm/new/", {"name": "Opportunite minimale"})
    assert response.status_code == 302

    with use_tenant(tenant.id):
        lead = CrmLead.objects.get(name="Opportunite minimale")
        assert lead.partner_id is None
        assert lead.priority == "medium"
        assert lead.expected_revenue_mga == 0
        assert lead.expected_close_date is None
        assert lead.team_id is None
        assert lead.description == ""


def test_lead_detail_move_stage(crm_screens_setup) -> None:
    client, tenant, lead = crm_screens_setup
    with use_tenant(tenant.id):
        target_stage = CrmStage.objects.get(code="qualified")

    response = client.post(
        f"/crm/{lead.id}/",
        {"action": "move_stage", "stage_id": str(target_stage.id)},
    )
    assert response.status_code == 302

    detail = client.get(f"/crm/{lead.id}/")
    assert b"Qualifie" in detail.content


def test_lead_list_screen_renders(crm_screens_setup) -> None:
    client, _tenant, _lead = crm_screens_setup
    response = client.get("/crm/")
    assert response.status_code == 200


def test_lead_detail_add_line_shows_in_table(crm_screens_setup) -> None:
    client, _tenant, lead = crm_screens_setup

    response = client.post(
        f"/crm/{lead.id}/",
        {
            "action": "add_line",
            "description": "Uniforme brode",
            "qty": "3",
            "unit_price": "15000",
            "discount_pct": "5",
        },
    )
    assert response.status_code == 302

    detail = client.get(f"/crm/{lead.id}/")
    assert detail.status_code == 200
    assert b"Uniforme brode" in detail.content


def test_lead_create_screen_preselects_tenant_default_pipeline(crm_screens_setup) -> None:
    """Le pipeline marque `is_default=True` du tenant (fixture `crm_screens_setup`) doit
    apparaitre deja selectionne dans le formulaire de creation d'opportunite, sans action de
    l'utilisateur — verifie l'attribut `selected` sur la bonne `<option>`, et l'absence de
    l'ancienne option vide "— Pipeline par defaut —"."""
    client, tenant, _lead = crm_screens_setup
    with use_tenant(tenant.id):
        default_pipeline = CrmPipeline.objects.get(tenant=tenant, is_default=True)

    response = client.get("/crm/new/")
    assert response.status_code == 200
    content = response.content.decode()

    expected_option = (
        f'<option value="{default_pipeline.id}" selected>{default_pipeline.name}</option>'
    )
    assert expected_option in content
    assert "Pipeline par défaut" not in content


def test_lead_detail_line_above_discount_threshold_requires_approval(crm_screens_setup) -> None:
    from django.contrib.auth.models import Group

    client, tenant, lead = crm_screens_setup
    with use_tenant(tenant.id):
        group, _ = Group.objects.get_or_create(name="commercial")
        user = User.objects.get(email="ui-crm@example.com")
        user.groups.add(group)

    response = client.post(
        f"/crm/{lead.id}/",
        {
            "action": "add_line",
            "description": "Combinaison sur mesure",
            "qty": "1",
            "unit_price": "50000",
            "discount_pct": "40",
        },
    )
    assert response.status_code == 200
    assert b"validation" in response.content.lower() or b"approbat" in response.content.lower()

    detail = client.get(f"/crm/{lead.id}/")
    assert b"Combinaison sur mesure" in detail.content
