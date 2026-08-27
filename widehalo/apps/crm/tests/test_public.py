"""Tests du contrat public de `crm` (`apps/crm/services/public.py`) — seule
surface que les autres apps metier ont le droit d'importer. Couvre ici le
gap ajoute pour RG-SAL-7 (S6 du sous-sequencement `sales`, cf. plan) :
`pipeline_weighted_demand`."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.crm.models import CrmLead
from apps.crm.services.public import get_lead_reference, pipeline_weighted_demand
from apps.crm.tests.factories import CrmLeadFactory, CrmLeadLineFactory, CrmStageFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def pipeline_setup():
    tenant = Tenant.objects.create(code="CRM-PUB", name="CRM Public Tenant")
    with use_tenant(tenant.id):
        return tenant


def test_get_lead_reference_returns_empty_for_unknown_lead(pipeline_setup) -> None:
    tenant = pipeline_setup
    with use_tenant(tenant.id):
        assert get_lead_reference(uuid.uuid4()) == ""


def test_pipeline_weighted_demand_sums_by_variant_for_open_leads(pipeline_setup) -> None:
    tenant = pipeline_setup
    with use_tenant(tenant.id):
        open_stage = CrmStageFactory(tenant=tenant, probability=40)
        variant_id = uuid.uuid4()
        lead = CrmLeadFactory(
            tenant=tenant, stage=open_stage, pipeline=open_stage.pipeline, probability=40
        )
        CrmLeadLineFactory(tenant=tenant, lead=lead, variant_id=variant_id, qty=Decimal("10"))

        other_lead = CrmLeadFactory(
            tenant=tenant, stage=open_stage, pipeline=open_stage.pipeline, probability=40
        )
        CrmLeadLineFactory(tenant=tenant, lead=other_lead, variant_id=variant_id, qty=Decimal("5"))

        result = pipeline_weighted_demand(tenant)
        # (10 * 40/100) + (5 * 40/100) = 4 + 2 = 6
        assert result[str(variant_id)] == Decimal("6")


def test_pipeline_weighted_demand_skips_won_and_lost_leads(pipeline_setup) -> None:
    tenant = pipeline_setup
    with use_tenant(tenant.id):
        won_stage = CrmStageFactory(tenant=tenant, probability=100, is_won=True)
        lost_stage = CrmStageFactory(
            tenant=tenant, pipeline=won_stage.pipeline, probability=0, is_lost=True
        )
        variant_id = uuid.uuid4()

        won_lead = CrmLeadFactory(tenant=tenant, stage=won_stage, pipeline=won_stage.pipeline)
        CrmLeadLineFactory(tenant=tenant, lead=won_lead, variant_id=variant_id, qty=Decimal("10"))

        lost_lead = CrmLeadFactory(tenant=tenant, stage=lost_stage, pipeline=won_stage.pipeline)
        CrmLeadLineFactory(tenant=tenant, lead=lost_lead, variant_id=variant_id, qty=Decimal("10"))

        assert pipeline_weighted_demand(tenant) == {}


def test_pipeline_weighted_demand_skips_lines_without_variant(pipeline_setup) -> None:
    tenant = pipeline_setup
    with use_tenant(tenant.id):
        open_stage = CrmStageFactory(tenant=tenant, probability=50)
        lead = CrmLeadFactory(tenant=tenant, stage=open_stage, pipeline=open_stage.pipeline)
        CrmLeadLineFactory(
            tenant=tenant, lead=lead, variant_id=None, is_custom=True, qty=Decimal("3")
        )

        assert pipeline_weighted_demand(tenant) == {}


def test_pipeline_weighted_demand_returns_empty_without_any_lead(pipeline_setup) -> None:
    tenant = pipeline_setup
    with use_tenant(tenant.id):
        assert pipeline_weighted_demand(tenant) == {}
        # `CrmLead` importe uniquement pour verifier l'absence de donnees —
        # pas de couplage supplementaire introduit.
        assert not CrmLead.objects.exists()
