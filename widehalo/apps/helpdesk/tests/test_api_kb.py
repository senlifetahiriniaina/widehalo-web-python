"""HD3 : tests API django-ninja pour la base de connaissances/gabarits de
reponse, la suggestion de reponse IA, et l'idempotence de l'integration
chat interne (`get_or_create_document_channel`)."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.helpdesk.services.tickets import create_ticket

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
    tenant = Tenant.objects.create(code="HLP-KB-API", name="Helpdesk KB API Tenant")
    user = User.objects.create_user(email="kb-api@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "commercial")
    return tenant, user


def test_create_and_publish_article_then_view_increments_count(api_helpdesk) -> None:
    tenant, user = api_helpdesk
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/helpdesk/kb/articles",
        {"title": "Comment configurer son mot de passe", "body": "Etapes..."},
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200, create_response.json()
    article_id = create_response.json()["id"]
    assert create_response.json()["is_published"] is False

    publish_response = client.post(f"/api/v1/helpdesk/kb/articles/{article_id}/publish", **headers)
    assert publish_response.status_code == 200
    assert publish_response.json()["is_published"] is True

    get_response = client.get(f"/api/v1/helpdesk/kb/articles/{article_id}", **headers)
    assert get_response.json()["view_count"] == 1

    get_response_2 = client.get(f"/api/v1/helpdesk/kb/articles/{article_id}", **headers)
    assert get_response_2.json()["view_count"] == 2


def test_kb_article_feedback_endpoint(api_helpdesk) -> None:
    tenant, user = api_helpdesk
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/helpdesk/kb/articles",
        {"title": "Article", "body": "Corps"},
        content_type="application/json",
        **headers,
    )
    article_id = create_response.json()["id"]

    feedback_response = client.post(
        f"/api/v1/helpdesk/kb/articles/{article_id}/feedback",
        {"helpful": True},
        content_type="application/json",
        **headers,
    )
    assert feedback_response.status_code == 200
    assert feedback_response.json()["helpful_count"] == 1
    assert feedback_response.json()["not_helpful_count"] == 0


def test_kb_article_third_party_cannot_publish_without_change_permission(api_helpdesk) -> None:
    """RBAC N3 symetrique a `user_can_manage_ticket` : un utilisateur
    sans `helpdesk.change_hlpkbarticle` peut publier SON PROPRE article
    mais pas celui d'un tiers."""
    tenant, user = api_helpdesk
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/helpdesk/kb/articles",
        {"title": "Article de l'auteur", "body": "Corps"},
        content_type="application/json",
        **headers,
    )
    article_id = create_response.json()["id"]

    other_user = User.objects.create_user(
        email="kb-third-party@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(other_user, "commercial")
    other_token = _access_token(client, other_user.email, "Str0ngPassw0rd!23")
    other_headers = _headers(other_token, str(tenant.id))

    forbidden_response = client.post(
        f"/api/v1/helpdesk/kb/articles/{article_id}/publish", **other_headers
    )
    assert forbidden_response.status_code == 403

    own_response = client.post(f"/api/v1/helpdesk/kb/articles/{article_id}/publish", **headers)
    assert own_response.status_code == 200
    assert own_response.json()["is_published"] is True


def test_response_template_crud(api_helpdesk) -> None:
    tenant, user = api_helpdesk
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/helpdesk/response-templates",
        {"name": "Accuse de reception", "category": "accueil", "body": "Bonjour, ..."},
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200, create_response.json()

    list_response = client.get("/api/v1/helpdesk/response-templates", **headers)
    assert len(list_response.json()["results"]) == 1


def test_suggest_reply_endpoint_never_errors_without_real_provider(api_helpdesk) -> None:
    tenant, user = api_helpdesk
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/helpdesk/tickets",
        {"subject": "Ticket pour suggestion", "kind": "demande"},
        content_type="application/json",
        **headers,
    )
    ticket_id = create_response.json()["id"]

    response = client.post(f"/api/v1/helpdesk/tickets/{ticket_id}/suggest-reply", **headers)
    assert response.status_code == 200
    assert response.json()["suggestion"] == ""


def test_chat_channel_idempotent_across_two_detail_page_loads(api_helpdesk) -> None:
    """Verifie le contrat de `get_or_create_document_channel` (cf. sa
    docstring) : deux appels successifs pour le MEME ticket renvoient le
    MEME canal, jamais un doublon."""
    tenant, user = api_helpdesk
    with use_tenant(tenant.id):
        ticket = create_ticket(tenant, subject="Ticket avec chat", requester=user)

    from apps.chat.models import ChatChannel
    from apps.chat.services.public import get_or_create_document_channel

    with use_tenant(tenant.id):
        first_channel_id = get_or_create_document_channel(
            tenant=tenant, content_object=ticket, participants=[user], title=ticket.subject
        )
        second_channel_id = get_or_create_document_channel(
            tenant=tenant, content_object=ticket, participants=[user], title=ticket.subject
        )

        assert first_channel_id == second_channel_id
        assert ChatChannel.objects.filter(tenant=tenant, object_id=str(ticket.pk)).count() == 1
