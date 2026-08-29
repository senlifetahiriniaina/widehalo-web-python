"""Factories factory_boy pour les modeles du module `projects` (PJ1-PJ5) —
une par modele concret (couche T1 du plan de durcissement, CDC §14
couches)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import factory

from apps.projects.models import (
    PrjBudgetLine,
    PrjCustomFieldDefinition,
    PrjInvoicingRecord,
    PrjProject,
    PrjSprint,
    PrjTask,
    PrjTaskDependency,
    PrjTeamMember,
    PrjTimeEntry,
)


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


class PrjSprintFactory(factory.django.DjangoModelFactory):
    """PJ6 — sprint agile."""

    class Meta:
        model = PrjSprint

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    project = factory.SubFactory(PrjProjectFactory, tenant=factory.SelfAttribute("..tenant"))
    name = factory.Sequence(lambda n: f"Sprint {n}")
    start_date = factory.LazyFunction(lambda: dt.date.today())
    end_date = factory.LazyFunction(lambda: dt.date.today() + dt.timedelta(days=13))
    status = PrjSprint.STATUS_PLANNED
    goal = ""


class PrjInvoicingRecordFactory(factory.django.DjangoModelFactory):
    """PJ5 — trace de facturation projet."""

    class Meta:
        model = PrjInvoicingRecord

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    project = factory.SubFactory(PrjProjectFactory, tenant=factory.SelfAttribute("..tenant"))
    mode = PrjInvoicingRecord.MODE_FIXED
    amount = Decimal("1000.0000")
    invoice_id = factory.LazyFunction(uuid.uuid4)
    billed_date = factory.LazyFunction(lambda: dt.date.today())


class PrjTeamMemberFactory(factory.django.DjangoModelFactory):
    """PJ7 — affectation d'un utilisateur a un projet."""

    class Meta:
        model = PrjTeamMember

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    project = factory.SubFactory(PrjProjectFactory, tenant=factory.SelfAttribute("..tenant"))
    user = factory.SubFactory("apps.core.tests.factories.UserFactory")
    role = "developpeur"
    allocation_pct = 50


class PrjTimeEntryFactory(factory.django.DjangoModelFactory):
    """PJ8 — entree de suivi du temps."""

    class Meta:
        model = PrjTimeEntry

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    task = factory.SubFactory(PrjTaskFactory, tenant=factory.SelfAttribute("..tenant"))
    user = factory.SubFactory("apps.core.tests.factories.UserFactory")
    started_at = factory.LazyFunction(lambda: dt.datetime.now(dt.UTC))
    stopped_at = factory.LazyAttribute(lambda o: o.started_at + dt.timedelta(hours=1))
    duration_minutes = 60
    billable = True
    billed = False


class PrjCustomFieldDefinitionFactory(factory.django.DjangoModelFactory):
    """PJ7 — definition de champ personnalise (projet/tache)."""

    class Meta:
        model = PrjCustomFieldDefinition

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    entity_type = PrjCustomFieldDefinition.ENTITY_TASK
    field_key = factory.Sequence(lambda n: f"champ_{n}")
    field_label = factory.Sequence(lambda n: f"Champ {n}")
    field_type = PrjCustomFieldDefinition.FIELD_TYPE_TEXT
    validation_rule = factory.LazyFunction(dict)
