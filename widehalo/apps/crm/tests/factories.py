"""Factories factory_boy pour les modeles du module `crm` — une par modele
concret (couche T1 du plan de durcissement, CDC §14 couches).

`tenant` est resolu via un `SubFactory` a chemin pointe vers
`apps.core.tests.factories.TenantFactory` (resolution paresseuse,
fonctionne meme si ce module est ecrit en parallele par un autre agent).
`partner_id`/`variant_id` sont toujours de simples UUID (jamais de FK
Django vers `apps.partners`/`apps.catalog` — regle de couplage n°1)."""

from __future__ import annotations

import uuid

import factory

from apps.crm.models import (
    CrmActivity,
    CrmLead,
    CrmLeadLine,
    CrmLostReason,
    CrmPipeline,
    CrmStage,
    CrmTeam,
)


class CrmPipelineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CrmPipeline

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Pipeline {n}")


class CrmStageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CrmStage

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    pipeline = factory.SubFactory(CrmPipelineFactory, tenant=factory.SelfAttribute("..tenant"))
    code = factory.Sequence(lambda n: f"STAGE{n}")
    name = factory.Sequence(lambda n: f"Etape {n}")


class CrmTeamFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CrmTeam

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Equipe {n}")


class CrmLostReasonFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CrmLostReason

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Motif de perte {n}")


class CrmLeadFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CrmLead

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Opportunite {n}")
    partner_id = factory.LazyFunction(uuid.uuid4)
    pipeline = factory.SubFactory(CrmPipelineFactory, tenant=factory.SelfAttribute("..tenant"))
    stage = factory.SubFactory(
        CrmStageFactory,
        tenant=factory.SelfAttribute("..tenant"),
        pipeline=factory.SelfAttribute("..pipeline"),
    )


class CrmLeadLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CrmLeadLine

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    lead = factory.SubFactory(CrmLeadFactory, tenant=factory.SelfAttribute("..tenant"))
    variant_id = factory.LazyFunction(uuid.uuid4)
    description = factory.Sequence(lambda n: f"Ligne {n}")
    qty = 1


class CrmActivityFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CrmActivity

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    lead = factory.SubFactory(CrmLeadFactory, tenant=factory.SelfAttribute("..tenant"))
    activity_type = CrmActivity.TYPE_CALL
    subject = factory.Sequence(lambda n: f"Appel de suivi {n}")
