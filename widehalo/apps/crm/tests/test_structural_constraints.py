"""T2 (couches 4-5 du CDC, §8) : contraintes structurelles/d'interdependance
au niveau base pour `crm` — comportement `on_delete` (PROTECT/CASCADE/
SET_NULL) de chaque FK du modele. Aucun `CHECK`/`UniqueConstraint` explicite
n'est declare sur ce module (verifie dans `apps/crm/models.py`).

RLS (isolation tenant) est hors-perimetre (couverte ailleurs)."""

from __future__ import annotations

import pytest
from django.db.models.deletion import ProtectedError

from apps.core.tests.factories import TenantFactory, UserFactory
from apps.core.tests.utils import use_tenant
from apps.crm.models import CrmActivity, CrmLead, CrmLeadLine
from apps.crm.tests.factories import (
    CrmActivityFactory,
    CrmLeadFactory,
    CrmLeadLineFactory,
    CrmLostReasonFactory,
    CrmPipelineFactory,
    CrmStageFactory,
    CrmTeamFactory,
)

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------
# on_delete=PROTECT
# --------------------------------------------------------------------------


def test_pipeline_cannot_be_deleted_while_referenced_by_a_lead() -> None:
    """`CrmLead.pipeline` est PROTECT : une opportunite bloque la
    suppression de son pipeline, meme si `CrmStage.pipeline` est CASCADE."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        lead = CrmLeadFactory(tenant=tenant)
        pipeline = lead.pipeline

        with pytest.raises(ProtectedError):
            pipeline.delete()


def test_stage_cannot_be_deleted_while_referenced_by_a_lead() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        lead = CrmLeadFactory(tenant=tenant)
        stage = lead.stage

        with pytest.raises(ProtectedError):
            stage.delete()


def test_pipeline_with_only_stages_and_no_leads_can_be_deleted() -> None:
    """Sans opportunite rattachee, la CASCADE `CrmStage.pipeline` joue
    normalement : le pipeline et ses etapes disparaissent ensemble."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        pipeline = CrmPipelineFactory(tenant=tenant)
        stage = CrmStageFactory(tenant=tenant, pipeline=pipeline)
        stage_id = stage.id

        pipeline.delete()

        from apps.crm.models import CrmStage

        assert not CrmStage.objects.filter(pk=stage_id).exists()


# --------------------------------------------------------------------------
# on_delete=CASCADE
# --------------------------------------------------------------------------


def test_deleting_a_lead_cascades_to_its_lines() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        line = CrmLeadLineFactory(tenant=tenant)
        lead = line.lead
        line_id = line.id

        lead.delete()

        assert not CrmLeadLine.objects.filter(pk=line_id).exists()


def test_deleting_a_lead_cascades_to_its_activities() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        activity = CrmActivityFactory(tenant=tenant)
        lead = activity.lead
        activity_id = activity.id

        lead.delete()

        assert not CrmActivity.objects.filter(pk=activity_id).exists()


# --------------------------------------------------------------------------
# on_delete=SET_NULL
# --------------------------------------------------------------------------


def test_deleting_a_salesperson_nullifies_the_lead() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        salesperson = UserFactory()
        lead = CrmLeadFactory(tenant=tenant, salesperson=salesperson)

        salesperson.delete()
        lead.refresh_from_db()

        assert lead.salesperson_id is None


def test_deleting_a_team_nullifies_the_lead() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        team = CrmTeamFactory(tenant=tenant)
        lead = CrmLeadFactory(tenant=tenant, team=team)

        team.delete()
        lead.refresh_from_db()

        assert lead.team_id is None


def test_deleting_a_lost_reason_nullifies_the_lead() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        lost_reason = CrmLostReasonFactory(tenant=tenant)
        lead = CrmLeadFactory(tenant=tenant, lost_reason=lost_reason)

        lost_reason.delete()
        lead.refresh_from_db()

        assert lead.lost_reason_id is None


def test_deleting_a_team_leader_nullifies_the_team() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        leader = UserFactory()
        team = CrmTeamFactory(tenant=tenant, leader=leader)

        leader.delete()
        team.refresh_from_db()

        assert team.leader_id is None


def test_deleting_an_assignee_nullifies_the_activity() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        assignee = UserFactory()
        activity = CrmActivityFactory(tenant=tenant, assigned_to=assignee)

        assignee.delete()
        activity.refresh_from_db()

        assert activity.assigned_to_id is None


def test_deleting_a_lead_does_not_delete_the_pipeline_or_stage() -> None:
    """Sens inverse de la CASCADE : supprimer une opportunite ne doit pas
    entrainer la disparition du pipeline/de l'etape qu'elle referencait."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        lead = CrmLeadFactory(tenant=tenant)
        pipeline_id, stage_id = lead.pipeline_id, lead.stage_id

        lead.delete()

        from apps.crm.models import CrmPipeline, CrmStage

        assert CrmPipeline.objects.filter(pk=pipeline_id).exists()
        assert CrmStage.objects.filter(pk=stage_id).exists()
        assert not CrmLead.objects.filter(pk=lead.pk).exists()
