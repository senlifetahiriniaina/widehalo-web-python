"""Factories factory_boy pour les modeles du module `projects` (PJ1) —
une par modele concret (couche T1 du plan de durcissement, CDC §14
couches)."""

from __future__ import annotations

import factory

from apps.projects.models import PrjProject, PrjTask


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
