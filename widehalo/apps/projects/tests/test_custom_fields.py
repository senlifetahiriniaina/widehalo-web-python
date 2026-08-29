"""Tests PJ7 (validation de champs personnalises, `services/custom_
fields.py`) — cf. plan, section « Module `projects` », etape PJ7. Inclut
le test d'integration avec `services/tasks.py::create_task` (validation
AVANT ecriture, cf. sa docstring)."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.projects.models import PrjCustomFieldDefinition
from apps.projects.services.custom_fields import validate_custom_fields
from apps.projects.services.projects import create_project
from apps.projects.services.tasks import create_task
from apps.projects.tests.factories import PrjCustomFieldDefinitionFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant_ctx():
    tenant = Tenant.objects.create(code="PRJ-CFD", name="Projects Custom Fields Tenant")
    with use_tenant(tenant.id):
        yield tenant


def test_validate_custom_fields_no_definitions_is_a_noop(tenant_ctx) -> None:
    validate_custom_fields(tenant_ctx, PrjCustomFieldDefinition.ENTITY_TASK, {"anything": 1})


def test_validate_custom_fields_rejects_missing_required(tenant_ctx) -> None:
    tenant = tenant_ctx
    PrjCustomFieldDefinitionFactory(
        tenant=tenant,
        entity_type=PrjCustomFieldDefinition.ENTITY_TASK,
        field_key="budget_code",
        field_type=PrjCustomFieldDefinition.FIELD_TYPE_TEXT,
        validation_rule={"required": True},
    )
    with pytest.raises(ValidationError):
        validate_custom_fields(tenant, PrjCustomFieldDefinition.ENTITY_TASK, {})


def test_validate_custom_fields_accepts_valid_text(tenant_ctx) -> None:
    tenant = tenant_ctx
    PrjCustomFieldDefinitionFactory(
        tenant=tenant,
        entity_type=PrjCustomFieldDefinition.ENTITY_TASK,
        field_key="budget_code",
        field_type=PrjCustomFieldDefinition.FIELD_TYPE_TEXT,
        validation_rule={"required": True},
    )
    validate_custom_fields(tenant, PrjCustomFieldDefinition.ENTITY_TASK, {"budget_code": "BC-42"})


def test_validate_custom_fields_rejects_invalid_choice(tenant_ctx) -> None:
    tenant = tenant_ctx
    PrjCustomFieldDefinitionFactory(
        tenant=tenant,
        entity_type=PrjCustomFieldDefinition.ENTITY_TASK,
        field_key="priority",
        field_type=PrjCustomFieldDefinition.FIELD_TYPE_CHOICE,
        validation_rule={"choices": ["low", "medium", "high"]},
    )
    with pytest.raises(ValidationError):
        validate_custom_fields(tenant, PrjCustomFieldDefinition.ENTITY_TASK, {"priority": "urgent"})
    # Une valeur valide passe.
    validate_custom_fields(tenant, PrjCustomFieldDefinition.ENTITY_TASK, {"priority": "high"})


def test_validate_custom_fields_rejects_number_out_of_bounds(tenant_ctx) -> None:
    tenant = tenant_ctx
    PrjCustomFieldDefinitionFactory(
        tenant=tenant,
        entity_type=PrjCustomFieldDefinition.ENTITY_TASK,
        field_key="effort_score",
        field_type=PrjCustomFieldDefinition.FIELD_TYPE_NUMBER,
        validation_rule={"min": 0, "max": 100},
    )
    with pytest.raises(ValidationError):
        validate_custom_fields(tenant, PrjCustomFieldDefinition.ENTITY_TASK, {"effort_score": 150})
    with pytest.raises(ValidationError):
        validate_custom_fields(tenant, PrjCustomFieldDefinition.ENTITY_TASK, {"effort_score": -1})
    validate_custom_fields(tenant, PrjCustomFieldDefinition.ENTITY_TASK, {"effort_score": 50})


def test_validate_custom_fields_rejects_wrong_type(tenant_ctx) -> None:
    tenant = tenant_ctx
    PrjCustomFieldDefinitionFactory(
        tenant=tenant,
        entity_type=PrjCustomFieldDefinition.ENTITY_TASK,
        field_key="is_billable",
        field_type=PrjCustomFieldDefinition.FIELD_TYPE_BOOLEAN,
    )
    with pytest.raises(ValidationError):
        validate_custom_fields(tenant, PrjCustomFieldDefinition.ENTITY_TASK, {"is_billable": "yes"})


def test_validate_custom_fields_rejects_invalid_date(tenant_ctx) -> None:
    tenant = tenant_ctx
    PrjCustomFieldDefinitionFactory(
        tenant=tenant,
        entity_type=PrjCustomFieldDefinition.ENTITY_TASK,
        field_key="kickoff_date",
        field_type=PrjCustomFieldDefinition.FIELD_TYPE_DATE,
    )
    with pytest.raises(ValidationError):
        validate_custom_fields(
            tenant, PrjCustomFieldDefinition.ENTITY_TASK, {"kickoff_date": "not-a-date"}
        )
    validate_custom_fields(
        tenant, PrjCustomFieldDefinition.ENTITY_TASK, {"kickoff_date": "2026-03-01"}
    )


def test_validate_custom_fields_scoped_by_entity_type(tenant_ctx) -> None:
    """Une definition `entity_type=project` ne s'applique jamais a une
    validation `entity_type=task` (et inversement)."""
    tenant = tenant_ctx
    PrjCustomFieldDefinitionFactory(
        tenant=tenant,
        entity_type=PrjCustomFieldDefinition.ENTITY_PROJECT,
        field_key="budget_code",
        field_type=PrjCustomFieldDefinition.FIELD_TYPE_TEXT,
        validation_rule={"required": True},
    )
    # Aucune definition `task` -> aucune exigence, meme cle absente.
    validate_custom_fields(tenant, PrjCustomFieldDefinition.ENTITY_TASK, {})


# --- Integration avec create_task ---------------------------------------------------


def test_create_task_rejects_invalid_custom_fields(tenant_ctx) -> None:
    tenant = tenant_ctx
    project = create_project(tenant, name="Projet avec champs personnalises")
    PrjCustomFieldDefinitionFactory(
        tenant=tenant,
        entity_type=PrjCustomFieldDefinition.ENTITY_TASK,
        field_key="priority",
        field_type=PrjCustomFieldDefinition.FIELD_TYPE_CHOICE,
        validation_rule={"choices": ["low", "medium", "high"]},
    )
    with pytest.raises(ValidationError):
        create_task(tenant, project=project, custom_fields={"priority": "urgent"})


def test_create_task_accepts_valid_custom_fields(tenant_ctx) -> None:
    tenant = tenant_ctx
    project = create_project(tenant, name="Projet avec champs personnalises valides")
    PrjCustomFieldDefinitionFactory(
        tenant=tenant,
        entity_type=PrjCustomFieldDefinition.ENTITY_TASK,
        field_key="priority",
        field_type=PrjCustomFieldDefinition.FIELD_TYPE_CHOICE,
        validation_rule={"choices": ["low", "medium", "high"]},
    )
    task = create_task(tenant, project=project, custom_fields={"priority": "high"})
    assert task.custom_fields == {"priority": "high"}


def test_create_task_without_custom_fields_still_works(tenant_ctx) -> None:
    """Aucune regression pour les appelants existants qui n'ont jamais eu
    besoin de `custom_fields` (parametre optionnel, cf. `services/tasks.
    py::create_task`)."""
    tenant = tenant_ctx
    project = create_project(tenant, name="Projet sans champs personnalises")
    task = create_task(tenant, project=project)
    assert task.custom_fields == {}
