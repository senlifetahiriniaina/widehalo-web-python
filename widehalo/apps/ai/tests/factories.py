"""Factories factory_boy pour les modeles du module `ai` — une par modele
concret (couche T1 du plan de durcissement, CDC §14 couches)."""

from __future__ import annotations

import factory

from apps.ai.models import AiRequest, AiUsageLimit


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
