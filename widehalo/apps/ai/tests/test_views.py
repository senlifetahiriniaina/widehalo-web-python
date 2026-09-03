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


def test_ai_launcher_fragment_renders_form_without_navigation(web_ai) -> None:
    tenant, user = web_ai
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get("/ai/launcher/")
    assert response.status_code == 200
    assert b"sales" in response.content  # module reellement enregistre au demarrage
    assert b"ai-launcher-result" in response.content
    assert b"<html" not in response.content  # fragment, jamais {% extends %}


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


def test_recommendations_screen_renders_without_query_params(web_ai) -> None:
    tenant, user = web_ai
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get("/ai/recommendations/")
    assert response.status_code == 200
    assert b"Recommandations d'action" in response.content


def test_data_query_screen_renders_without_question(web_ai) -> None:
    tenant, user = web_ai
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get("/ai/data-query/")
    assert response.status_code == 200
    assert b"Questions-donnees IA" in response.content


def test_data_query_screen_surfaces_consulted_tool_labels(web_ai, monkeypatch) -> None:
    # Sprint 11 (L7 IA gateway) — "presentation des reponses/actions IA" :
    # l'ecran doit lister LISIBLEMENT (label du registre, pas juste le
    # `code` technique persiste dans `AiDataQuery.tools_called`) les tools
    # reellement consultes par le LLM pour composer sa reponse, jamais
    # presenter la reponse comme une boite noire.
    tenant, user = web_ai

    def _fake_ask(question, *, tenant, user, locale):
        from apps.ai.tests.factories import AiDataQueryFactory

        return AiDataQueryFactory(
            tenant=tenant,
            question=question,
            tools_called=[{"code": "sales.revenue_report", "args": {}}],
        )

    monkeypatch.setattr("apps.ai.views.run_data_query_ask", _fake_ask)

    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get("/ai/data-query/", {"question": "quel est le CA du mois dernier ?"})
    assert response.status_code == 200
    assert b"Sources consult\xc3\xa9es" in response.content
    # Le label lisible du registre (pas seulement le code technique) doit
    # apparaitre dans le rendu (apostrophe HTML-echappee par Django, donc
    # verifiee sur la partie sans apostrophe du libelle).
    assert b"SAL-CA" in response.content
    assert b"sales" in response.content


def test_recommendations_screen_renders_suggestions_for_a_context(web_ai, monkeypatch) -> None:
    tenant, user = web_ai

    def _fake_suggest(module, action, *, tenant, role_code):
        from apps.ai.tests.factories import AiRecommendationFactory

        return [
            AiRecommendationFactory(
                tenant=tenant, context_module=module, context_action=action, role_code=role_code
            )
        ]

    monkeypatch.setattr("apps.ai.views.run_action_advisor", _fake_suggest)

    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get("/ai/recommendations/", {"module": "purchase", "action": "consulter"})
    assert response.status_code == 200
    assert b"Recommandation de test (factory)." in response.content
