"""Factories factory_boy pour les modeles du module `projects` (PJ1-PJ2) —
une par modele concret (couche T1 du plan de durcissement, CDC §14
couches)."""

from __future__ import annotations

import factory

from apps.projects.models import PrjProject, PrjTask, PrjTaskDependency


class PrjProjectFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PrjProject

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Projet {n}")
    methodology = PrjProject.METHODOLOGY_WATERFALL


class PrjTaskFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PrjTask

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    project = factory.SubFactory(PrjProjectFactory, tenant=factory.SelfAttribute("..tenant"))
    task_type = PrjTask.TYPE_TASK


class PrjTaskDependencyFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PrjTaskDependency

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    from_task = factory.SubFactory(PrjTaskFactory, tenant=factory.SelfAttribute("..tenant"))
    to_task = factory.SubFactory(
        PrjTaskFactory,
        tenant=factory.SelfAttribute("..tenant"),
        project=factory.SelfAttribute("..from_task.project"),
    )
    dependency_type = PrjTaskDependency.TYPE_FINISH_TO_START
