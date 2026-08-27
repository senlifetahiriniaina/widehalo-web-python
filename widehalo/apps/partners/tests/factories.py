"""Factories factory_boy pour les modeles du module `partners` — une par
modele concret (couche T1 du plan de durcissement, CDC §14 couches).

`tenant` est resolu via un `SubFactory` a chemin pointe vers
`apps.core.tests.factories.TenantFactory` (resolution paresseuse)."""

from __future__ import annotations

import factory

from apps.partners.models import DuplicateAlert, Partner


class PartnerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Partner

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Partenaire {n}")
    roles = factory.LazyFunction(lambda: [Partner.ROLE_CLIENT])
    nif = factory.Sequence(lambda n: f"NIF{n:08d}")


class DuplicateAlertFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DuplicateAlert

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    partner = factory.SubFactory(PartnerFactory, tenant=factory.SelfAttribute("..tenant"))
    duplicate_of = factory.SubFactory(PartnerFactory, tenant=factory.SelfAttribute("..tenant"))
    matched_field = "nif"
