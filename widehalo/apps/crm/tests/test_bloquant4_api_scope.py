"""Bloquants (4/4) — RG-CRM-5 tenu par la vue web, oublie par l'API.

`views.lead_detail` repasse par `scope_leads_for_user` et le commente en
quinze lignes : « n'importe quel utilisateur authentifie du tenant pouvait
consulter ET agir sur N'IMPORTE QUEL lead par simple connaissance de son
UUID ». Le correctif n'a jamais atteint `apps/crm/api.py`, ou QUATRE
endpoints faisaient `get_object_or_404(CrmLead, id=lead_id)` tout court —
alors que `list_leads`, dans le meme fichier, scopait correctement.

La regle etait donc tenue sur une surface et oubliee sur l'autre : le meme
motif exactement qu'`applicable_taxes` (correcte) face a
`get_default_sale_tax` (qui ignorait le regime fiscal).

Ce n'est PAS une fuite entre tenants — celle-la tient par RLS. C'est le
perimetre INTERNE, celui que RG-CRM-5 definit : un commercial ne voit que
ses propres opportunites. Il pouvait pourtant deplacer, gagner ou perdre
celle d'un collegue, y ajouter une activite, ou forcer une remise."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.crm.models import CrmPipeline, CrmStage
from apps.crm.services.leads import create_lead_quick

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ngPassw0rd!23"


def _token(client: Client, email: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        {"email": email, "password": PASSWORD},
        content_type="application/json",
    )
    return response.json()["access"]


def _headers(token: str, tenant_id: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": tenant_id}


@pytest.fixture
def two_salespeople():
    """Deux commerciaux du MEME tenant, chacun avec sa propre opportunite.

    Le meme tenant est essentiel : un test a deux tenants prouverait
    l'isolation RLS, qui n'a jamais ete en cause. C'est le perimetre
    interne qu'il faut exercer."""
    tenant = Tenant.objects.create(code="CRM-B4", name="CRM Perimetre SARL")
    mine = User.objects.create_user(email="mine-b4@example.com", password=PASSWORD)
    theirs = User.objects.create_user(email="theirs-b4@example.com", password=PASSWORD)
    grant_role(mine, "commercial")
    grant_role(theirs, "commercial")
    with use_tenant(tenant.id):
        pipeline = CrmPipeline.objects.create(tenant=tenant, name="Ventes", is_default=True)
        CrmStage.objects.create(
            tenant=tenant, pipeline=pipeline, code="nouveau", name="Nouveau", sequence=1
        )
        won = CrmStage.objects.create(
            tenant=tenant, pipeline=pipeline, code="gagne", name="Gagne", sequence=2, is_won=True
        )
        my_lead = create_lead_quick(tenant=tenant, name="La mienne", salesperson=mine)
        their_lead = create_lead_quick(tenant=tenant, name="Celle du collegue", salesperson=theirs)
    return tenant, mine, my_lead, their_lead, won


def test_a_salesperson_cannot_move_a_colleagues_opportunity(two_salespeople) -> None:
    """L'egalite qui etait fausse : 200 la ou il fallait 404.

    404 et non 403, comme la vue web et comme les bulletins de paie
    (RG-PAY-9) : distinguer « n'existe pas » de « existe mais hors portee »
    revient a confirmer l'existence de l'enregistrement d'autrui."""
    tenant, mine, _my_lead, their_lead, won = two_salespeople
    client = Client()
    headers = _headers(_token(client, mine.email), str(tenant.id))

    response = client.post(
        f"/api/v1/crm/leads/{their_lead.id}/move-stage",
        {"stage_id": str(won.id)},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 404

    with use_tenant(tenant.id):
        their_lead.refresh_from_db()
    assert their_lead.stage_id != won.id


def test_a_salesperson_cannot_read_or_write_a_colleagues_activities(two_salespeople) -> None:
    """Les trois autres endpoints, qui portaient le meme trou."""
    tenant, mine, _my_lead, their_lead, _won = two_salespeople
    client = Client()
    headers = _headers(_token(client, mine.email), str(tenant.id))

    assert client.get(f"/api/v1/crm/leads/{their_lead.id}/activities", **headers).status_code == 404
    assert (
        client.post(
            f"/api/v1/crm/leads/{their_lead.id}/activities",
            {"activity_type": "call", "subject": "Intrusion"},
            content_type="application/json",
            **headers,
        ).status_code
        == 404
    )
    with use_tenant(tenant.id):
        assert not their_lead.activities.exists()


def test_the_owner_still_moves_their_own_opportunity(two_salespeople) -> None:
    """La falsification. Sans elle, « le perimetre est applique » et « le
    perimetre bloque tout le monde » seraient indiscernables — et la
    seconde casserait le module entier."""
    tenant, mine, my_lead, _their_lead, won = two_salespeople
    client = Client()
    headers = _headers(_token(client, mine.email), str(tenant.id))

    response = client.post(
        f"/api/v1/crm/leads/{my_lead.id}/move-stage",
        {"stage_id": str(won.id)},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200

    with use_tenant(tenant.id):
        my_lead.refresh_from_db()
    assert my_lead.stage_id == won.id
