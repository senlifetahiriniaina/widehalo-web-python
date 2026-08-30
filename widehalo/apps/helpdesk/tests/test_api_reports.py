"""HD4 : tests API (JWT reel via `django.test.Client`, meme patron que
`test_api.py`) des endpoints CSAT et rapports."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.helpdesk.services.tickets import assign_ticket, create_ticket, resolve_ticket

pytestmark = pytest.mark.django_db


def _access_token(client: Client, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        {"email": email, "password": password},
        content_type="application/json",
    )
    return response.json()["access"]


def _headers(token: str, tenant_id: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": tenant_id}


@pytest.fixture
def api_helpdesk():
    tenant = Tenant.objects.create(code="HLP-RPT-API", name="Helpdesk Reports API Tenant")
    requester = User.objects.create_user(
        email="requester-rpt@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(requester, "commercial")
    agent = User.objects.create_user(email="agent-rpt@example.com", password="Str0ngPassw0rd!23")
    grant_role(agent, "commercial")
    return tenant, requester, agent


def test_csat_submission_flow_via_api(api_helpdesk) -> None:
    tenant, requester, agent = api_helpdesk
    with use_tenant(tenant.id):
        ticket = create_ticket(tenant, subject="Test", requester=requester, kind="incident")
        assign_ticket(ticket, agent, assignee=agent)
        resolve_ticket(ticket, agent)

    client = Client()
    token = _access_token(client, requester.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    # Pas encore de reponse CSAT -> 404.
    get_before = client.get(f"/api/v1/helpdesk/tickets/{ticket.id}/csat", **headers)
    assert get_before.status_code == 404

    submit = client.post(
        f"/api/v1/helpdesk/tickets/{ticket.id}/csat",
        {"score": 5, "comment": "Impeccable."},
        content_type="application/json",
        **headers,
    )
    assert submit.status_code == 200
    assert submit.json()["score"] == 5

    get_after = client.get(f"/api/v1/helpdesk/tickets/{ticket.id}/csat", **headers)
    assert get_after.status_code == 200
    assert get_after.json()["comment"] == "Impeccable."

    # Deuxieme soumission -> refusee (400, `ValidationError`).
    second = client.post(
        f"/api/v1/helpdesk/tickets/{ticket.id}/csat",
        {"score": 1},
        content_type="application/json",
        **headers,
    )
    assert second.status_code == 400


def test_csat_submission_forbidden_for_non_requester(api_helpdesk) -> None:
    """`agent` est l'assigne (pas le demandeur) : n'a pas le droit de
    soumettre la reponse CSAT a la place du demandeur (cf. `_can_submit_csat`,
    disclosed dans `apps.helpdesk.api`)."""
    tenant, requester, agent = api_helpdesk
    with use_tenant(tenant.id):
        ticket = create_ticket(tenant, subject="Test", requester=requester, kind="incident")
        assign_ticket(ticket, agent, assignee=agent)
        resolve_ticket(ticket, agent)

    client = Client()
    token = _access_token(client, agent.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        f"/api/v1/helpdesk/tickets/{ticket.id}/csat",
        {"score": 5},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 403


def test_reports_endpoints_are_reachable_by_a_standard_role(api_helpdesk) -> None:
    """`helpdesk.view_hlpticket` est deja accorde a TOUS les roles non
    admin/direction (cf. `rbac_policy.py`) : les 4 endpoints de rapport
    doivent donc etre accessibles a un simple `commercial`."""
    tenant, requester, agent = api_helpdesk
    with use_tenant(tenant.id):
        ticket = create_ticket(tenant, subject="Test", requester=requester, kind="incident")
        assign_ticket(ticket, agent, assignee=agent)
        resolve_ticket(ticket, agent)

    client = Client()
    token = _access_token(client, requester.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    for path in (
        "/api/v1/helpdesk/reports/csat",
        "/api/v1/helpdesk/reports/agent-performance",
        "/api/v1/helpdesk/reports/team-benchmark",
        "/api/v1/helpdesk/reports/sla-compliance",
    ):
        response = client.get(path, **headers)
        assert response.status_code == 200, path
