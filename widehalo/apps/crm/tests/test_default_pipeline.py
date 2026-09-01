"""Pipeline commercial par defaut (HubSpot, 7 etapes) charge automatiquement
a l'initialisation d'une entreprise — cf. `apps.crm.services.pipelines`."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.crm.models import CrmPipeline, CrmStage
from apps.crm.services.pipelines import DEFAULT_PIPELINE_NAME, ensure_default_pipeline

pytestmark = pytest.mark.django_db


def test_ensure_default_pipeline_creates_seven_stages() -> None:
    tenant = Tenant.objects.create(code="CRM-PIPE-1", name="CRM Pipe 1", country_code="MG")
    with use_tenant(tenant.id):
        pipeline = ensure_default_pipeline(tenant)

        assert pipeline.name == DEFAULT_PIPELINE_NAME
        assert pipeline.is_default is True
        stages = list(
            CrmStage.objects.filter(tenant=tenant, pipeline=pipeline).order_by("sequence")
        )
        assert len(stages) == 7
        assert [s.code for s in stages] == [
            "appointment_scheduled",
            "qualified_to_buy",
            "presentation_scheduled",
            "decision_maker_bought_in",
            "contract_sent",
            "closed_won",
            "closed_lost",
        ]
        assert [s.probability for s in stages] == [20, 40, 60, 80, 90, 100, 0]
        won = stages[-2]
        lost = stages[-1]
        assert won.is_won is True
        assert lost.is_lost is True
        assert lost.requires_reason is True


def test_ensure_default_pipeline_is_idempotent() -> None:
    tenant = Tenant.objects.create(code="CRM-PIPE-2", name="CRM Pipe 2", country_code="MG")
    with use_tenant(tenant.id):
        first = ensure_default_pipeline(tenant)
        second = ensure_default_pipeline(tenant)

        assert first.id == second.id
        assert CrmPipeline.objects.filter(tenant=tenant).count() == 1
        assert CrmStage.objects.filter(tenant=tenant, pipeline=first).count() == 7


def test_ensure_default_pipeline_reuses_an_existing_default_pipeline() -> None:
    tenant = Tenant.objects.create(code="CRM-PIPE-3", name="CRM Pipe 3", country_code="MG")
    with use_tenant(tenant.id):
        existing = CrmPipeline.objects.create(tenant=tenant, name="Deja present", is_default=True)

        pipeline = ensure_default_pipeline(tenant)

        assert pipeline.id == existing.id
        assert CrmPipeline.objects.filter(tenant=tenant).count() == 1
        # Aucune etape n'est creee sur un pipeline par defaut deja existant
        # d'une autre origine — la fonction ne cree des etapes que pour le
        # pipeline qu'elle cree elle-meme.
        assert CrmStage.objects.filter(tenant=tenant, pipeline=pipeline).count() == 0


def test_load_default_pipeline_command_is_idempotent() -> None:
    tenant = Tenant.objects.create(code="CRM-PIPE-4", name="CRM Pipe 4", country_code="MG")
    call_command("load_default_pipeline", tenant=tenant.code)
    call_command("load_default_pipeline", tenant=tenant.code)

    with use_tenant(tenant.id):
        assert CrmPipeline.objects.filter(tenant=tenant, is_default=True).count() == 1
