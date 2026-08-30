"""HD1 : tests API django-ninja du module `helpdesk`, JWT reel via
`django.test.Client` — meme patron que `apps.logistics.tests.test_api`.

Discipline (garde-fou architecture `attempt_transition()`+`.save()`, cf.
`tests/architecture/test_attempt_transition_saves_state.py`) : chaque
transition FSM de `HlpTicket` est verifiee via un rechargement HTTP SEPARE
(nouvelle requete GET), jamais en reutilisant le meme objet Python en
memoire — lecon documentee du chantier `mrp` (cf. consigne de la tache)."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role

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
    # `commercial` (pas `admin`/`direction`/`comptable`/`rh`, cf.
    # `settings.CORE_MFA_REQUIRED_ROLES`) : evite le detour MFA dans ces
    # tests, non pertinent ici — a {view, add} sur `helpdesk`, suffisant
    # pour creer/consulter/transitionner SES PROPRES tickets (requester,
    # cf. scope N3).
    tenant = Tenant.objects.create(code="HLP-API", name="Helpdesk API Tenant")
    user = User.objects.create_user(email="helpdesk-api@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "commercial")
    return tenant, user


def test_create_ticket_and_list_via_api(api_helpdesk) -> None:
    tenant, user = api_helpdesk
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/helpdesk/tickets",
        {"subject": "Rupture de stock coton", "kind": "incident"},
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    body = create_response.json()
    assert body["state"] == "new"
    assert body["priority"] == "normal"
    assert body["reference"].startswith("HLP-")

    list_response = client.get("/api/v1/helpdesk/tickets", **headers)
    assert list_response.status_code == 200
    assert len(list_response.json()["results"]) == 1


def test_ticket_fsm_state_persists_across_separate_api_calls(api_helpdesk) -> None:
    """Chaque transition est verifiee par une requete GET SEPAREE — jamais
    en reutilisant l'objet Python de la reponse POST precedente (lecon du
    chantier `mrp`, cf. docstring de tete de fichier)."""
    tenant, user = api_helpdesk
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/helpdesk/tickets",
        {"subject": "Panne machine", "kind": "incident"},
        content_type="application/json",
        **headers,
    )
    ticket_id = create_response.json()["id"]
    assert create_response.json()["state"] == "new"

    for action, expected_state in [
        ("assign", "in_progress"),
        ("request-more-info", "pending"),
        ("resume", "in_progress"),
        ("resolve", "resolved"),
        ("close", "closed"),
    ]:
        response = client.post(f"/api/v1/helpdesk/tickets/{ticket_id}/{action}", **headers)
        assert response.status_code == 200, response.json()
        assert response.json()["state"] == expected_state

        get_response = client.get(f"/api/v1/helpdesk/tickets/{ticket_id}", **headers)
        assert get_response.json()["state"] == expected_state

    reopen_response = client.post(f"/api/v1/helpdesk/tickets/{ticket_id}/reopen", **headers)
    assert reopen_response.status_code == 200
    assert reopen_response.json()["state"] == "in_progress"

    get_response = client.get(f"/api/v1/helpdesk/tickets/{ticket_id}", **headers)
    assert get_response.json()["state"] == "in_progress"
    assert get_response.json()["resolved_at"] is None
    assert get_response.json()["closed_at"] is None


def test_forbidden_transition_returns_error(api_helpdesk) -> None:
    tenant, user = api_helpdesk
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/helpdesk/tickets",
        {"subject": "Demande materiel", "kind": "demande"},
        content_type="application/json",
        **headers,
    )
    ticket_id = create_response.json()["id"]

    # `resolve` n'est pas atteignable depuis `new` (seulement depuis
    # `in_progress`/`pending`) — la transition doit etre refusee.
    response = client.post(f"/api/v1/helpdesk/tickets/{ticket_id}/resolve", **headers)
    assert response.status_code == 400

    get_response = client.get(f"/api/v1/helpdesk/tickets/{ticket_id}", **headers)
    assert get_response.json()["state"] == "new"


def test_comment_marks_first_responded_at(api_helpdesk) -> None:
    tenant, user = api_helpdesk
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    other_agent = User.objects.create_user(
        email="agent-helpdesk@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(other_agent, "commercial")

    # `assignee_id` positionne des la creation : le scope N3
    # (`user_can_manage_ticket`) autorise ensuite `other_agent` a commenter
    # ce ticket (assignee), sans lui accorder `helpdesk.change_hlpticket`.
    create_response = client.post(
        "/api/v1/helpdesk/tickets",
        {"subject": "Demande acces", "kind": "demande", "assignee_id": str(other_agent.id)},
        content_type="application/json",
        **headers,
    )
    ticket_id = create_response.json()["id"]
    assert create_response.json()["first_responded_at"] is None

    agent_token = _access_token(client, other_agent.email, "Str0ngPassw0rd!23")
    agent_headers = _headers(agent_token, str(tenant.id))

    comment_response = client.post(
        f"/api/v1/helpdesk/tickets/{ticket_id}/comments",
        {"body": "Pris en charge, en cours d'analyse."},
        content_type="application/json",
        **agent_headers,
    )
    assert comment_response.status_code == 200, comment_response.json()

    get_response = client.get(f"/api/v1/helpdesk/tickets/{ticket_id}", **headers)
    assert get_response.json()["first_responded_at"] is not None


def test_n3_scoping_own_ticket_vs_third_party(api_helpdesk) -> None:
    """RBAC N3 (cf. plan) : un `collaborateur` sans `helpdesk.change_hlpticket`
    peut transitionner/commenter SON PROPRE ticket (requester) mais pas
    celui d'un tiers."""
    tenant, _admin = api_helpdesk
    client = Client()

    owner = User.objects.create_user(email="owner@example.com", password="Str0ngPassw0rd!23")
    grant_role(owner, "collaborateur")
    other = User.objects.create_user(email="other@example.com", password="Str0ngPassw0rd!23")
    grant_role(other, "collaborateur")

    owner_token = _access_token(client, owner.email, "Str0ngPassw0rd!23")
    owner_headers = _headers(owner_token, str(tenant.id))
    other_token = _access_token(client, other.email, "Str0ngPassw0rd!23")
    other_headers = _headers(other_token, str(tenant.id))

    create_response = client.post(
        "/api/v1/helpdesk/tickets",
        {"subject": "Mon ticket", "kind": "demande"},
        content_type="application/json",
        **owner_headers,
    )
    assert create_response.status_code == 200
    ticket_id = create_response.json()["id"]

    # Le proprietaire (requester) PEUT transitionner son propre ticket.
    own_response = client.post(f"/api/v1/helpdesk/tickets/{ticket_id}/assign", **owner_headers)
    assert own_response.status_code == 200
    assert own_response.json()["state"] == "in_progress"

    # Un tiers (`collaborateur`, ni requester ni assignee) NE PEUT PAS.
    third_party_response = client.post(
        f"/api/v1/helpdesk/tickets/{ticket_id}/request-more-info", **other_headers
    )
    assert third_party_response.status_code == 403

    get_response = client.get(f"/api/v1/helpdesk/tickets/{ticket_id}", **owner_headers)
    assert get_response.json()["state"] == "in_progress"
