"""Factories factory_boy pour les modeles du module `feasibility` — une par
modele concret (couche T1 du plan de durcissement, CDC §14 couches).

`tenant` est resolu via un `SubFactory` a chemin pointe vers
`apps.core.tests.factories.TenantFactory` (resolution paresseuse, meme
convention que tous les autres modules)."""

from __future__ import annotations

from decimal import Decimal

import factory

from apps.feasibility.models import SECTOR_TEXTILE, FeaStudy, FeaStudyLine


class FeaStudyFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FeaStudy

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Etude de faisabilite {n}")
    sector_code = SECTOR_TEXTILE


class FeaStudyLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FeaStudyLine

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    study = factory.SubFactory(FeaStudyFactory, tenant=factory.SelfAttribute("..tenant"))
    hypothetical_spec = factory.LazyFunction(lambda: {"name": "Produit hypothese"})
    assumed_qty = Decimal(10)
    assumed_unit_price_mga = Decimal(5000)
