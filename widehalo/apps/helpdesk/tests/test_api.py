"""HD1 : tests API django-ninja du module `helpdesk`, JWT reel via
`django.test.Client` — meme patron que `apps.logistics.tests.test_api`.

Discipline (garde-fou architecture `attempt_transition()`+`.save()`, cf.
`tests/architecture/test_attempt_transition_saves_state.py`) : chaque
transition FSM de `HlpTicket` est verifiee via un rechargement HTTP SEPARE
(nouvelle requete GET), jamais en reutilisant le meme objet Python en
memoire — lecon documentee du chantier `mrp` (cf. consigne de la tache)."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, Permission
from django.test import Client

from apps.core.models.event import EventLog
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.helpdesk.models import HlpEscalationEvent

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


def test_manual_escalation_creates_event_and_publishes_event(api_helpdesk) -> None:
    """HD2 : `escalate_ticket` (chemin manuel, API) cree EXACTEMENT un
    `HlpEscalationEvent` (`rule=None`/`escalated_by=<utilisateur appelant>`)
    et publie `"helpdesk.ticket_escalated"` — verifie par un rechargement
    SEPARE (nouvelle requete GET), jamais en reutilisant le meme objet
    Python en memoire (lecon documentee du chantier `mrp`)."""
    tenant, user = api_helpdesk
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/helpdesk/tickets",
        {"subject": "A escalader", "kind": "incident"},
        content_type="application/json",
        **headers,
    )
    ticket_id = create_response.json()["id"]

    escalate_response = client.post(f"/api/v1/helpdesk/tickets/{ticket_id}/escalate", **headers)
    assert escalate_response.status_code == 200, escalate_response.json()
    assert escalate_response.json()["state"] == "escalated"

    history_response = client.get(
        f"/api/v1/helpdesk/tickets/{ticket_id}/escalation-history", **headers
    )
    assert history_response.status_code == 200
    results = history_response.json()["results"]
    assert len(results) == 1
    assert results[0]["rule_id"] is None
    assert results[0]["escalated_by_id"] == str(user.id)

    # `HlpEscalationEvent.objects` (TenantManager) filtre sur le tenant
    # COURANT du contexte applicatif, absent ici (test hors requete HTTP,
    # le middleware qui active le tenant ne vit que le temps d'une requete
    # `Client.post`/`.get`) — `use_tenant()` explicite, meme discipline que
    # toute assertion de niveau modele apres un appel API dans ce depot.
    with use_tenant(tenant.id):
        assert HlpEscalationEvent.objects.filter(ticket_id=ticket_id).count() == 1
    assert EventLog.objects.filter(
        event_type="helpdesk.ticket_escalated", payload__ticket_id=ticket_id
    ).exists()


def test_sla_and_escalation_config_endpoints_require_admin_or_direction(api_helpdesk) -> None:
    """RBAC (cf. plan) : `helpdesk.manage_hlpslapolicy`/
    `manage_hlpescalationrule`/`run_helpdesk_checks` sont des permissions
    PERSONNALISEES accordees uniquement a `admin`/`direction` — un role
    "domaine cible" comme `commercial` (qui a pourtant {view, add} au
    niveau app sur `helpdesk`, cf. `ROLE_APP_PERMISSIONS`) n'y a PAS acces."""
    tenant, commercial_user = api_helpdesk
    client = Client()
    token = _access_token(client, commercial_user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    sla_response = client.post(
        "/api/v1/helpdesk/sla-policies",
        {
            "name": "Standard",
            "priority": "normal",
            "first_response_minutes": 60,
            "resolution_minutes": 480,
        },
        content_type="application/json",
        **headers,
    )
    assert sla_response.status_code == 403

    rule_response = client.post(
        "/api/v1/helpdesk/escalation-rules",
        {"name": "Regle", "condition_type": "time_since_created", "threshold_minutes": 60},
        content_type="application/json",
        **headers,
    )
    assert rule_response.status_code == 403

    run_response = client.post("/api/v1/helpdesk/checks/run", **headers)
    assert run_response.status_code == 403

    # `admin`/`direction` sont dans `CORE_MFA_REQUIRED_ROLES`, ce qui
    # bloquerait la connexion JWT de ce test tant qu'un device TOTP n'est
    # pas enrole (meme constat/meme contournement que `apps.automation.
    # tests.test_api`/`apps.financing.tests.test_api`) : groupe ad hoc
    # portant EXACTEMENT les 3 permissions personnalisees exercees, plutot
    # que `grant_role("admin")`.
    admin_user = User.objects.create_user(
        email="admin-helpdesk@example.com", password="Str0ngPassw0rd!23"
    )
    group, _ = Group.objects.get_or_create(name="helpdesk-config-api-test")
    group.permissions.set(
        Permission.objects.filter(
            content_type__app_label="helpdesk",
            codename__in=[
                "manage_hlpslapolicy",
                "manage_hlpescalationrule",
                "run_helpdesk_checks",
            ],
        )
    )
    admin_user.groups.add(group)
    admin_token = _access_token(client, admin_user.email, "Str0ngPassw0rd!23")
    admin_headers = _headers(admin_token, str(tenant.id))

    admin_sla_response = client.post(
        "/api/v1/helpdesk/sla-policies",
        {
            "name": "Standard",
            "priority": "normal",
            "first_response_minutes": 60,
            "resolution_minutes": 480,
        },
        content_type="application/json",
        **admin_headers,
    )
    assert admin_sla_response.status_code == 200, admin_sla_response.json()

    admin_run_response = client.post("/api/v1/helpdesk/checks/run", **admin_headers)
    assert admin_run_response.status_code == 200
