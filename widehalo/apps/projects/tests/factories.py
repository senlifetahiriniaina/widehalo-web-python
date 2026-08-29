"""Factories factory_boy pour les modeles du module `projects` (PJ1-PJ4) —
une par modele concret (couche T1 du plan de durcissement, CDC §14
couches)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import factory

from apps.projects.models import PrjBudgetLine, PrjProject, PrjTask, PrjTaskDependency


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


class PrjBudgetLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PrjBudgetLine

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    project = factory.SubFactory(PrjProjectFactory, tenant=factory.SelfAttribute("..tenant"))
    category = PrjBudgetLine.CATEGORY_OPEX
    label = factory.Sequence(lambda n: f"Ligne budgetaire {n}")
    planned_amount = Decimal("1000.0000")
    actual_amount = Decimal("0")
    period = factory.LazyFunction(lambda: dt.date.today().replace(day=1))
