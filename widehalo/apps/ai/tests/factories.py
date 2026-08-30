"""Factories factory_boy pour les modeles du module `ai` — une par modele
concret (couche T1 du plan de durcissement, CDC §14 couches)."""

from __future__ import annotations

import factory

from apps.ai.models import (
    AiAnomaly,
    AiDataQuery,
    AiInsight,
    AiRecommendation,
    AiRequest,
    AiUsageLimit,
)
from apps.core.services.anomaly_registry import SEVERITY_LOW


class AiUsageLimitFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AiUsageLimit

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    monthly_token_budget = 100_000
    alert_threshold_pct = 80
    hard_stop = True


class AiRequestFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AiRequest

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    feature = AiRequest.FEATURE_ASSIST
    prompt_tokens_estimate = 100
    completion_tokens_estimate = 50
    provider_backend = "stub"


class AiAnomalyFactory(factory.django.DjangoModelFactory):
    """AI3 — factory de test T1. `content_type`/`object_id` restent vides
    par defaut (meme choix par defaut que `RiskItemFactory` pour un
    rattachement optionnel) : un test qui a besoin d'un rattachement
    concret le fournit explicitement."""

    class Meta:
        model = AiAnomaly

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    check_code = "test.factory_check"
    severity = SEVERITY_LOW
    description = "Anomalie de test (factory)."


class AiInsightFactory(factory.django.DjangoModelFactory):
    """AI5 — factory de test T1."""

    class Meta:
        model = AiInsight

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    category = "ventes"
    title = "Insight de test (factory)."
    body = "Corps de l'insight de test (factory)."
    source_modules = factory.LazyFunction(lambda: ["sales"])
    is_ai_generated = False


class AiRecommendationFactory(factory.django.DjangoModelFactory):
    """AI7 — factory de test T1."""

    class Meta:
        model = AiRecommendation

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    context_module = "purchase"
    context_action = "consulter"
    role_code = "resp_commercial"
    label = "Recommandation de test (factory)."
    target_module = "purchase"
    target_action_code = ""


class AiDataQueryFactory(factory.django.DjangoModelFactory):
    """GW4 — factory de test T1."""

    class Meta:
        model = AiDataQuery

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    question = "Quel est le chiffre d'affaires du mois dernier ? (test factory)"
    tools_called = factory.LazyFunction(lambda: [{"code": "sales.revenue_report", "args": {}}])
    answer = "Reponse de test (factory)."
    succeeded = True
    provider_backend = "stub"
