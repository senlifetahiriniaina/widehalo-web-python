from __future__ import annotations

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role

pytestmark = pytest.mark.django_db


@pytest.fixture
def web_ai():
    # L'ecran ne verifie que `@login_required` (RBAC fin porte par l'API,
    # cf. docstring de `apps/ai/views.py`) — un role hors `CORE_MFA_
    # REQUIRED_ROLES` suffit pour `force_login` sans etre redirige vers
    # `/mfa/`.
    tenant = Tenant.objects.create(code="AI-WEB", name="AI Web Tenant")
    user = User.objects.create_user(email="ai-web@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "resp_commercial")
    return tenant, user


def test_usage_budget_screen_renders(web_ai) -> None:
    tenant, user = web_ai
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get("/ai/usage/")
    assert response.status_code == 200
    assert b"Budget de tokens IA" in response.content or b"tokens" in response.content


def test_assist_widget_screen_renders(web_ai) -> None:
    tenant, user = web_ai
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get("/ai/assist/")
    assert response.status_code == 200
    assert b"sales" in response.content  # module reellement enregistre au demarrage


def test_assist_fragment_returns_guidance(web_ai) -> None:
    tenant, user = web_ai
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.post("/ai/assist/fragment/", {"module": "sales", "action": "consulter"})
    assert response.status_code == 200
    assert response.content.strip()


def test_insights_list_screen_renders(web_ai) -> None:
    tenant, user = web_ai
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get("/ai/insights/")
    assert response.status_code == 200
    assert b"Insights proactifs" in response.content
