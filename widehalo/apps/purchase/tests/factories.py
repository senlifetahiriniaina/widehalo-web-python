"""Factories factory_boy pour les modeles du module `purchase` (PU1,
demande d'achat) — meme discipline que `apps.sales.tests.factories`.

`tenant` est resolu via un `SubFactory` a chemin pointe vers
`apps.core.tests.factories.TenantFactory` (resolution paresseuse, meme
patron que `apps.sales.tests.factories`). `variant_id`/`preferred_supplier_id`
sont toujours de simples UUID (jamais de FK Django vers `apps.catalog`/
`apps.partners` — regle de couplage n1)."""

from __future__ import annotations

import datetime as dt
import uuid

import factory

from apps.purchase.models import PurRequisition, PurRequisitionLine, PurSubstitute


class PurRequisitionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PurRequisition

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    requester = factory.SubFactory("apps.core.tests.factories.UserFactory")
    date_needed = factory.LazyFunction(dt.date.today)


class PurRequisitionLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PurRequisitionLine

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    requisition = factory.SubFactory(
        PurRequisitionFactory, tenant=factory.SelfAttribute("..tenant")
    )
    variant_id = factory.LazyFunction(uuid.uuid4)
    description = factory.Sequence(lambda n: f"Ligne {n}")
    qty = 1


class PurSubstituteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PurSubstitute

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    variant_id = factory.LazyFunction(uuid.uuid4)
    substitute_variant_id = factory.LazyFunction(uuid.uuid4)
    compatibility = PurSubstitute.COMPATIBILITY_EQUIVALENT
