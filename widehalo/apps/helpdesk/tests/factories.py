"""Factories factory_boy pour les modeles du module `helpdesk` — une par
modele concret (couche T1 du plan de durcissement, CDC §14 couches).

`tenant` est resolu via un `SubFactory` a chemin pointe vers
`apps.core.tests.factories.TenantFactory` (resolution paresseuse, meme
convention que tous les autres modules)."""

from __future__ import annotations

import factory
from django.utils import timezone

from apps.helpdesk.models import (
    KIND_DEMANDE,
    PRIORITY_NORMAL,
    HlpCsatResponse,
    HlpEscalationEvent,
    HlpEscalationRule,
    HlpKbArticle,
    HlpKbCategory,
    HlpResponseTemplate,
    HlpSlaBreach,
    HlpSlaPolicy,
    HlpTeam,
    HlpTicket,
    HlpTicketComment,
    HlpTicketTypeCatalog,
)


class HlpTeamFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = HlpTeam

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Equipe support {n}")
    description = "Equipe de test"


class HlpTicketTypeCatalogFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = HlpTicketTypeCatalog

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    kind = KIND_DEMANDE
    code = factory.Sequence(lambda n: f"test.code.{n}")
    label = factory.Sequence(lambda n: f"Type de test {n}")


class HlpTicketFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = HlpTicket

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    reference = factory.Sequence(lambda n: f"HLP-2026-{n:04d}")
    subject = factory.Sequence(lambda n: f"Ticket de test {n}")
    kind = KIND_DEMANDE
    requester = factory.SubFactory("apps.core.tests.factories.UserFactory")


class HlpTicketCommentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = HlpTicketComment

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    ticket = factory.SubFactory(HlpTicketFactory, tenant=factory.SelfAttribute("..tenant"))
    body = "Commentaire de test"


class HlpSlaPolicyFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = HlpSlaPolicy

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Politique SLA de test {n}")
    priority = PRIORITY_NORMAL
    first_response_minutes = 60
    resolution_minutes = 480


class HlpSlaBreachFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = HlpSlaBreach

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    ticket = factory.SubFactory(HlpTicketFactory, tenant=factory.SelfAttribute("..tenant"))
    breach_type = HlpSlaBreach.BREACH_FIRST_RESPONSE
    breached_at = factory.LazyFunction(timezone.now)
    minutes_over = 15


class HlpEscalationRuleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = HlpEscalationRule

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Regle d'escalade de test {n}")
    condition_type = HlpEscalationRule.CONDITION_TIME_SINCE_CREATED
    threshold_minutes = 120


class HlpEscalationEventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = HlpEscalationEvent

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    ticket = factory.SubFactory(HlpTicketFactory, tenant=factory.SelfAttribute("..tenant"))
    reason = "Escalade de test"


class HlpKbCategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = HlpKbCategory

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Categorie KB de test {n}")


class HlpKbArticleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = HlpKbArticle

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    title = factory.Sequence(lambda n: f"Article de test {n}")
    body = "Contenu de test."


class HlpResponseTemplateFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = HlpResponseTemplate

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Gabarit de test {n}")
    body = "Bonjour, ..."


class HlpCsatResponseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = HlpCsatResponse

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    ticket = factory.SubFactory(
        HlpTicketFactory,
        tenant=factory.SelfAttribute("..tenant"),
        state=HlpTicket.STATE_RESOLVED,
    )
    score = 5
    comment = "Tres satisfait."
