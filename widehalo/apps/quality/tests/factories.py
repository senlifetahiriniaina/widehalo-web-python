"""Factories `factory_boy` pour `apps.quality` — requises par T1
(`tests/architecture` et `apps/core/tests/test_tenant_portability_per_
entity.py::_FACTORY_MODULES` exigent une factory pour toute sous-classe
concrète de `BaseModel`). Gap pré-existant depuis D1 (jamais corrigé,
jamais exécuté dans le même run que les tests dédiés de `apps.quality`,
même situation que `pos`/`simulation` documentée dans
`test_tenant_portability_per_entity.py`) — corrigé à l'occasion de D3, et
étendu ici (D5) pour `QltRecallDossier` (D4), même gap réapparu à
l'identique pour ce cinquième modèle jamais suivi de factory.

Même patron que `apps.core.tests.factories.RiskItemFactory` : rattachement
générique `content_type`/`object_id` jamais renseigné par défaut (cas
d'usage optionnel, cf. docstring des modèles)."""

from __future__ import annotations

from decimal import Decimal

import factory
from django.utils import timezone

from apps.core.tests.factories import TenantFactory, UserFactory
from apps.quality.models import (
    QltControlPlan,
    QltCriticalPoint,
    QltMeasurement,
    QltNonConformity,
    QltRecallDossier,
)


class QltControlPlanFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = QltControlPlan

    tenant = factory.SubFactory(TenantFactory)
    name = factory.Sequence(lambda n: f"Plan de contrôle {n}")
    frequency_days = 7


class QltCriticalPointFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = QltCriticalPoint

    tenant = factory.SubFactory(TenantFactory)
    control_plan = factory.SubFactory(
        QltControlPlanFactory, tenant=factory.SelfAttribute("..tenant")
    )
    name = factory.Sequence(lambda n: f"Point critique {n}")
    limit_min = Decimal("0")
    limit_max = Decimal("100")


class QltMeasurementFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = QltMeasurement

    tenant = factory.SubFactory(TenantFactory)
    critical_point = factory.SubFactory(
        QltCriticalPointFactory, tenant=factory.SelfAttribute("..tenant")
    )
    value = Decimal("50")
    measured_by = factory.SubFactory(UserFactory)
    measured_at = factory.LazyFunction(timezone.now)


class QltNonConformityFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = QltNonConformity

    tenant = factory.SubFactory(TenantFactory)
    description = factory.Sequence(lambda n: f"Non-conformité {n}")
    opened_by = factory.SubFactory(UserFactory)


class QltRecallDossierFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = QltRecallDossier

    tenant = factory.SubFactory(TenantFactory)
    reason = factory.Sequence(lambda n: f"Rappel {n}")
    initiated_by = factory.SubFactory(UserFactory)
