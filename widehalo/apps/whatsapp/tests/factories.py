"""Factories factory_boy pour les modeles du module `whatsapp`."""

from __future__ import annotations

from decimal import Decimal

import factory

from apps.whatsapp.models import WaConversation, WaMessageTemplate


class WaMessageTemplateFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = WaMessageTemplate

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"modele-{n}")
    name = factory.Sequence(lambda n: f"Modèle {n}")
    category = WaMessageTemplate.CATEGORY_UTILITY
    body_text = "Bonjour {{nom_client}}, votre commande est prête."
    variables = factory.LazyFunction(lambda: ["nom_client"])
    estimated_cost_ariary = Decimal("50")


class WaConversationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = WaConversation

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    phone_number = factory.Sequence(lambda n: f"+26134000{n:04d}")
