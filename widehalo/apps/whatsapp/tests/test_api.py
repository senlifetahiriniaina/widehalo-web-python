from __future__ import annotations

import json

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.whatsapp.models import WaConversation, WaMessageTemplate
from apps.whatsapp.services.consent import grant_consent
from apps.whatsapp.services.templates import approve_template, create_template, submit_for_review

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
def api_whatsapp():
    tenant = Tenant.objects.create(code="WA-API", name="WhatsApp API Tenant")
    user = User.objects.create_user(email="whatsapp-api@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "commercial")
    return tenant, user


def test_create_submit_approve_template_via_api(api_whatsapp) -> None:
    tenant, user = api_whatsapp
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/whatsapp/templates",
        {"code": "welcome", "name": "Bienvenue", "category": "utility", "body_text": "Bonjour"},
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    template_id = create_response.json()["id"]
    assert create_response.json()["status"] == WaMessageTemplate.STATUS_DRAFT

    submit_response = client.post(f"/api/v1/whatsapp/templates/{template_id}/submit", **headers)
    assert submit_response.status_code == 200
    assert submit_response.json()["status"] == WaMessageTemplate.STATUS_PENDING_REVIEW

    approve_response = client.post(f"/api/v1/whatsapp/templates/{template_id}/approve", **headers)
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == WaMessageTemplate.STATUS_APPROVED


def test_grant_and_revoke_consent_via_api(api_whatsapp) -> None:
    tenant, user = api_whatsapp
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    grant_response = client.post(
        "/api/v1/whatsapp/consent/grant",
        {"phone_number": "+261340000040", "source": "formulaire_web"},
        content_type="application/json",
        **headers,
    )
    assert grant_response.status_code == 200
    assert grant_response.json()["has_active_consent"] is True

    revoke_response = client.post(
        "/api/v1/whatsapp/consent/revoke",
        {"phone_number": "+261340000040"},
        content_type="application/json",
        **headers,
    )
    assert revoke_response.status_code == 200
    assert revoke_response.json()["has_active_consent"] is False


def test_send_message_via_api_blocked_without_consent(api_whatsapp) -> None:
    tenant, user = api_whatsapp
    with use_tenant(tenant.id):
        template = create_template(
            tenant,
            code="promo",
            name="Promo",
            category=WaMessageTemplate.CATEGORY_MARKETING,
            body_text="Promo",
        )
        submit_for_review(template)
        approve_template(template, user=user)
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/whatsapp/send",
        {"phone_number": "+261340000041", "template_code": "promo"},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 400


def test_list_templates_and_conversations_via_api(api_whatsapp) -> None:
    tenant, user = api_whatsapp
    with use_tenant(tenant.id):
        create_template(
            tenant,
            code="tpl",
            name="Modèle",
            category=WaMessageTemplate.CATEGORY_UTILITY,
            body_text="...",
        )
        grant_consent(tenant, phone_number="+261340000042", source="formulaire_web")
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    templates_response = client.get("/api/v1/whatsapp/templates", **headers)
    assert templates_response.status_code == 200
    assert len(templates_response.json()["results"]) == 1

    conversations_response = client.get("/api/v1/whatsapp/conversations", **headers)
    assert conversations_response.status_code == 200
    assert len(conversations_response.json()["results"]) == 1


def test_retry_messages_endpoint_requires_custom_permission(api_whatsapp) -> None:
    tenant, _admin = api_whatsapp
    outsider = User.objects.create_user(email="outsider@example.com", password="Str0ngPassw0rd!23")
    grant_role(outsider, "collaborateur")
    client = Client()
    token = _access_token(client, outsider.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post("/api/v1/whatsapp/messages/retry", **headers)
    assert response.status_code == 403


def test_governed_webhook_processes_message_when_default_tenant_configured(
    api_whatsapp, settings
) -> None:
    tenant, _user = api_whatsapp
    settings.WHATSAPP_DEFAULT_TENANT_ID = str(tenant.id)
    client = Client()

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "+261340000043",
                                    "text": {"body": "Bonjour"},
                                    "id": "wamid.governed",
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    response = client.post(
        "/api/v1/whatsapp/webhook", data=json.dumps(payload), content_type="application/json"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["processed"] == 1
    assert body["governed"] is True

    with use_tenant(tenant.id):
        assert WaConversation.objects.filter(tenant=tenant, phone_number="+261340000043").exists()


def test_governed_webhook_degrades_gracefully_without_default_tenant(settings) -> None:
    settings.WHATSAPP_DEFAULT_TENANT_ID = ""
    client = Client()

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "+261340000044",
                                    "text": {"body": "Bonjour"},
                                    "id": "wamid.ungoverned",
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    response = client.post(
        "/api/v1/whatsapp/webhook", data=json.dumps(payload), content_type="application/json"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["processed"] == 1
    assert body["governed"] is False
