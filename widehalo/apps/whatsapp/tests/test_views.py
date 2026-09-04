from __future__ import annotations

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.whatsapp.models import WaMessageTemplate
from apps.whatsapp.services.consent import grant_consent
from apps.whatsapp.services.templates import approve_template, create_template, submit_for_review

pytestmark = pytest.mark.django_db


@pytest.fixture
def web_whatsapp():
    # "commercial" est le role "domaine cible" de `whatsapp` (cf.
    # rbac_policy.py) et n'est pas dans CORE_MFA_REQUIRED_ROLES.
    tenant = Tenant.objects.create(code="WA-WEB", name="WhatsApp Web Tenant")
    user = User.objects.create_user(email="whatsapp-web@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "commercial")
    return tenant, user


def _logged_client(tenant: Tenant, user: User) -> Client:
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def test_conversations_screen_requires_login() -> None:
    tenant = Tenant.objects.create(code="WA-WEB-ANON", name="WhatsApp Anon Tenant")
    client = Client()
    response = client.get("/whatsapp/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 302


def test_conversations_screen_renders(web_whatsapp) -> None:
    tenant, user = web_whatsapp
    client = _logged_client(tenant, user)
    response = client.get("/whatsapp/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200
    assert "Conversations WhatsApp" in response.content.decode()


def test_config_screen_renders(web_whatsapp) -> None:
    tenant, user = web_whatsapp
    client = _logged_client(tenant, user)
    response = client.get("/whatsapp/config/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200
    assert "Configuration WhatsApp" in response.content.decode()


def test_consent_grant_and_revoke_flow(web_whatsapp) -> None:
    tenant, user = web_whatsapp
    client = _logged_client(tenant, user)

    grant_response = client.post(
        "/whatsapp/consent/grant/",
        {"phone_number": "+261340000030", "source": "formulaire_web"},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert grant_response.status_code == 302

    with use_tenant(tenant.id):
        from apps.whatsapp.models import WaConversation

        conversation = WaConversation.objects.get(tenant=tenant, phone_number="+261340000030")
        assert conversation.has_active_consent() is True

    revoke_response = client.post(
        "/whatsapp/consent/revoke/",
        {"phone_number": "+261340000030"},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert revoke_response.status_code == 302
    conversation.refresh_from_db()
    assert conversation.has_active_consent() is False


def test_template_create_submit_approve_flow(web_whatsapp) -> None:
    tenant, user = web_whatsapp
    client = _logged_client(tenant, user)

    create_response = client.post(
        "/whatsapp/templates/new/",
        {"code": "bienvenue", "name": "Bienvenue", "category": "utility", "body_text": "Bonjour"},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert create_response.status_code == 302

    with use_tenant(tenant.id):
        template = WaMessageTemplate.objects.get(tenant=tenant, code="bienvenue")
        assert template.status == WaMessageTemplate.STATUS_DRAFT

    submit_response = client.post(
        f"/whatsapp/templates/{template.id}/submit/", HTTP_X_TENANT_ID=str(tenant.id)
    )
    assert submit_response.status_code == 302
    template.refresh_from_db()
    assert template.status == WaMessageTemplate.STATUS_PENDING_REVIEW

    approve_response = client.post(
        f"/whatsapp/templates/{template.id}/approve/", HTTP_X_TENANT_ID=str(tenant.id)
    )
    assert approve_response.status_code == 302
    template.refresh_from_db()
    assert template.status == WaMessageTemplate.STATUS_APPROVED


def test_send_message_screen_requires_consent(web_whatsapp) -> None:
    tenant, user = web_whatsapp
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
    client = _logged_client(tenant, user)

    response = client.post(
        "/whatsapp/send/",
        {"phone_number": "+261340000031", "template_code": "promo"},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert response.status_code == 302
    assert "error=" in response.url


def test_send_message_screen_succeeds_with_consent(web_whatsapp) -> None:
    tenant, user = web_whatsapp
    with use_tenant(tenant.id):
        grant_consent(tenant, phone_number="+261340000032", source="formulaire_web")
        template = create_template(
            tenant,
            code="promo2",
            name="Promo",
            category=WaMessageTemplate.CATEGORY_MARKETING,
            body_text="Promo",
        )
        submit_for_review(template)
        approve_template(template, user=user)
    client = _logged_client(tenant, user)

    response = client.post(
        "/whatsapp/send/",
        {"phone_number": "+261340000032", "template_code": "promo2"},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert response.status_code == 302
    assert "error=" not in response.url
