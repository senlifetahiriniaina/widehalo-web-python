"""Factories factory_boy pour les modeles du module `chat` — une par modele
concret (couche T1 du plan de durcissement, CDC §14 couches).

`tenant` est resolu via un `SubFactory` a chemin pointe vers
`apps.core.tests.factories.TenantFactory` (resolution paresseuse)."""

from __future__ import annotations

import factory

from apps.chat.models import ChatChannel, ChatChannelMembership, ChatMessage


class ChatChannelFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ChatChannel

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    kind = ChatChannel.KIND_CONTEXT
    title = factory.Sequence(lambda n: f"Canal {n}")


class ChatChannelMembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ChatChannelMembership

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    channel = factory.SubFactory(ChatChannelFactory, tenant=factory.SelfAttribute("..tenant"))
    user = factory.SubFactory("apps.core.tests.factories.UserFactory")


class ChatMessageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ChatMessage

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    channel = factory.SubFactory(ChatChannelFactory, tenant=factory.SelfAttribute("..tenant"))
    sender = factory.SubFactory("apps.core.tests.factories.UserFactory")
    body = factory.Sequence(lambda n: f"Message {n}")
