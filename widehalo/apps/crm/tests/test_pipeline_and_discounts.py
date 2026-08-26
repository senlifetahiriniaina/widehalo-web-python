from __future__ import annotations

from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.crm.models import CrmLostReason, CrmPipeline, CrmStage
from apps.crm.services.discounts import (
    DiscountApprovalRequiredError,
    enforce_discount_threshold,
    max_discount_for_user,
)
from apps.crm.services.leads import add_lead_line, create_lead_quick
from apps.crm.services.pipeline import move_lead_to_stage

pytestmark = pytest.mark.django_db


@pytest.fixture
def pipeline_setup():
    tenant = Tenant.objects.create(code="CRM-PIPE", name="CRM Pipeline Tenant")
    with use_tenant(tenant.id):
        pipeline = CrmPipeline.objects.create(tenant=tenant, name="Ventes", is_default=True)
        new_stage = CrmStage.objects.create(
            tenant=tenant, pipeline=pipeline, code="nouveau", name="Nouveau", sequence=1
        )
        qualified_stage = CrmStage.objects.create(
            tenant=tenant,
            pipeline=pipeline,
            code="qualifie",
            name="Qualifie",
            sequence=2,
            probability=40,
        )
        won_stage = CrmStage.objects.create(
            tenant=tenant,
            pipeline=pipeline,
            code="gagne",
            name="Gagne",
            sequence=3,
            probability=100,
            is_won=True,
        )
        lost_stage = CrmStage.objects.create(
            tenant=tenant,
            pipeline=pipeline,
            code="perdu",
            name="Perdu",
            sequence=4,
            is_lost=True,
        )
        lost_reason = CrmLostReason.objects.create(tenant=tenant, name="Prix trop eleve")
        return tenant, pipeline, new_stage, qualified_stage, won_stage, lost_stage, lost_reason


def test_move_lead_to_next_stage_updates_probability(pipeline_setup) -> None:
    tenant, _pipeline, _new, qualified, *_ = pipeline_setup
    with use_tenant(tenant.id):
        lead = create_lead_quick(tenant=tenant, name="Opportunite")
        moved = move_lead_to_stage(lead, qualified)
        assert moved.stage_id == qualified.id
        assert moved.probability == 40


def test_moving_to_won_stage_sets_won_at(pipeline_setup) -> None:
    tenant, _pipeline, _new, qualified, won, *_ = pipeline_setup
    with use_tenant(tenant.id):
        lead = create_lead_quick(tenant=tenant, name="Opportunite")
        move_lead_to_stage(lead, qualified)
        won_lead = move_lead_to_stage(lead, won)
        assert won_lead.won_at is not None


def test_moving_to_lost_stage_without_reason_is_rejected(pipeline_setup) -> None:
    tenant, _pipeline, _new, _qualified, _won, lost, _reason = pipeline_setup
    with use_tenant(tenant.id):
        lead = create_lead_quick(tenant=tenant, name="Opportunite")
        with pytest.raises(ValidationError):
            move_lead_to_stage(lead, lost)


def test_moving_to_lost_stage_with_reason_and_comment_succeeds(pipeline_setup) -> None:
    tenant, _pipeline, _new, _qualified, _won, lost, reason = pipeline_setup
    with use_tenant(tenant.id):
        lead = create_lead_quick(tenant=tenant, name="Opportunite")
        lost_lead = move_lead_to_stage(lead, lost, lost_reason=reason, comment="Trop cher")
        assert lost_lead.lost_reason_id == reason.id
        assert lost_lead.lost_at is not None


def test_terminal_stage_cannot_be_left(pipeline_setup) -> None:
    tenant, _pipeline, _new, qualified, won, *_ = pipeline_setup
    with use_tenant(tenant.id):
        lead = create_lead_quick(tenant=tenant, name="Opportunite")
        move_lead_to_stage(lead, qualified)
        move_lead_to_stage(lead, won)
        with pytest.raises(ValidationError):
            move_lead_to_stage(lead, qualified)


def test_discount_within_cap_needs_no_approval(pipeline_setup) -> None:
    tenant, *_ = pipeline_setup
    with use_tenant(tenant.id):
        commercial = User.objects.create_user(email="com@example.com", password="Str0ngPassw0rd!23")
        Group.objects.get_or_create(name="commercial")[0].user_set.add(commercial)

        lead = create_lead_quick(tenant=tenant, name="Opportunite")
        line = add_lead_line(
            lead,
            description="Produit",
            qty=Decimal(1),
            unit_price=Decimal(1000),
            discount_pct=Decimal(5),
            is_custom=True,
        )
        enforce_discount_threshold(line, requested_by=commercial)  # ne doit pas lever


def test_discount_above_cap_requires_approval(pipeline_setup) -> None:
    tenant, *_ = pipeline_setup
    with use_tenant(tenant.id):
        commercial = User.objects.create_user(
            email="com2@example.com", password="Str0ngPassw0rd!23"
        )
        Group.objects.get_or_create(name="commercial")[0].user_set.add(commercial)

        lead = create_lead_quick(tenant=tenant, name="Opportunite")
        line = add_lead_line(
            lead,
            description="Produit",
            qty=Decimal(1),
            unit_price=Decimal(1000),
            discount_pct=Decimal(25),
            is_custom=True,
        )
        with pytest.raises(DiscountApprovalRequiredError):
            enforce_discount_threshold(line, requested_by=commercial)


def test_discount_cap_defaults_to_unlimited_for_unmapped_roles(pipeline_setup) -> None:
    tenant, *_ = pipeline_setup
    with use_tenant(tenant.id):
        direction = User.objects.create_user(email="dir@example.com", password="Str0ngPassw0rd!23")
        Group.objects.get_or_create(name="direction")[0].user_set.add(direction)
        assert max_discount_for_user(direction) == Decimal(100)
