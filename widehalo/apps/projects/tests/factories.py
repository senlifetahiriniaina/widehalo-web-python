"""Factories factory_boy pour les modeles du module `projects` (PJ1-PJ5) —
une par modele concret (couche T1 du plan de durcissement, CDC §14
couches)."""

from __future__ import annotations

import datetime as dt
import secrets
import uuid
from decimal import Decimal

import factory

from apps.projects.models import (
    PrjBudgetLine,
    PrjCustomFieldDefinition,
    PrjGuestAccess,
    PrjInvoicingRecord,
    PrjProject,
    PrjSprint,
    PrjTask,
    PrjTaskDependency,
    PrjTeamMember,
    PrjTimeEntry,
    PrjWikiPage,
)
from apps.projects.services.guest_portal import hash_token


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


class PrjWikiPageFactory(factory.django.DjangoModelFactory):
    """PJ10 — page de wiki projet."""

    class Meta:
        model = PrjWikiPage

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    project = factory.SubFactory(PrjProjectFactory, tenant=factory.SelfAttribute("..tenant"))
    title = factory.Sequence(lambda n: f"Page {n}")
    body = "Contenu de la page."
    author = factory.SubFactory("apps.core.tests.factories.UserFactory")


class PrjGuestAccessFactory(factory.django.DjangoModelFactory):
    """PJ14 — lien de portail invite. Le jeton est genere via
    `secrets.token_urlsafe` (jamais une sequence previsible), meme discipline
    que `services/guest_portal.py::create_guest_access`.

    Depuis L15 la base ne porte que `token_hash`. La fabrique reproduit donc
    exactement le contrat du service : elle genere le jeton en clair, stocke
    son empreinte, et repose le jeton sur l'instance en `plaintext_token`.
    Sans cela, aucun test ne pourrait exercer `resolve_guest_access` — et une
    fabrique qui ne se comporte pas comme la production fait passer des tests
    qui ne prouvent rien."""

    class Meta:
        model = PrjGuestAccess

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    project = factory.SubFactory(PrjProjectFactory, tenant=factory.SelfAttribute("..tenant"))
    guest_email = factory.Sequence(lambda n: f"invite{n}@example.com")
    expires_at = factory.LazyFunction(lambda: dt.datetime.now(dt.UTC) + dt.timedelta(days=7))
    permissions = PrjGuestAccess.PERMISSIONS_READ_ONLY

    @classmethod
    def _create(cls, model_class, *args, **kwargs):  # type: ignore[no-untyped-def]
        # `plaintext_token` accepte en entree pour les tests qui ont besoin
        # d'un jeton connu d'avance ; genere sinon.
        plaintext = kwargs.pop("plaintext_token", None) or secrets.token_urlsafe(32)
        kwargs.setdefault("token_hash", hash_token(plaintext))
        instance = super()._create(model_class, *args, **kwargs)
        instance.plaintext_token = plaintext
        return instance
