"""Factories factory_boy pour les modèles du module `bi`."""

from __future__ import annotations

import factory
from django.utils import timezone

from apps.bi.models import BiDashboard, BiDiffusionLog, BiReport


class BiReportFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BiReport

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"rapport-{n}")
    name = factory.Sequence(lambda n: f"Rapport {n}")
    owner = factory.SubFactory("apps.core.tests.factories.UserFactory")
    definition = factory.LazyFunction(
        lambda: {"metric_codes": ["sales.ca_ht"], "dimensions": ["temps"], "filters": []}
    )
    is_published = True


class BiDashboardFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BiDashboard

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Tableau de bord {n}")
    owner = factory.SubFactory("apps.core.tests.factories.UserFactory")
    tiles = factory.LazyFunction(list)


class BiDiffusionLogFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BiDiffusionLog

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    report = factory.SubFactory(BiReportFactory, tenant=factory.SelfAttribute("..tenant"))
    recipient = "destinataire@example.com"
    status = BiDiffusionLog.STATUS_SENT
    sent_at = factory.LazyFunction(timezone.now)
