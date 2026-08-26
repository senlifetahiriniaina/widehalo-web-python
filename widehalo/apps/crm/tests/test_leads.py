from __future__ import annotations

from decimal import Decimal

import pytest

from apps.catalog.models import ProductTemplate, ProductVariant, UnitOfMeasure
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.crm.models import CrmLeadLine, CrmPipeline, CrmStage
from apps.crm.services.leads import add_lead_line, create_lead_quick

pytestmark = pytest.mark.django_db


@pytest.fixture
def crm_setup():
    tenant = Tenant.objects.create(code="CRM-T", name="CRM Tenant")
    with use_tenant(tenant.id):
        pipeline = CrmPipeline.objects.create(tenant=tenant, name="Ventes", is_default=True)
        CrmStage.objects.create(
            tenant=tenant, pipeline=pipeline, code="nouveau", name="Nouveau", sequence=1
        )
        CrmStage.objects.create(
            tenant=tenant, pipeline=pipeline, code="qualifie", name="Qualifie", sequence=2
        )
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PC", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )
        template = ProductTemplate.objects.create(
            tenant=tenant,
            name="T-Shirt",
            base_uom=uom,
            reference="TPL-CRM-0001",
            base_price_mga=Decimal("15000"),
        )
        variant = ProductVariant.objects.create(
            tenant=tenant, template=template, reference="VAR-CRM-0001"
        )
        return tenant, pipeline, variant


def test_create_lead_quick_assigns_default_pipeline_and_first_stage(crm_setup) -> None:
    tenant, pipeline, _variant = crm_setup
    with use_tenant(tenant.id):
        lead = create_lead_quick(tenant=tenant, name="Opportunite Alpha")
        assert lead.pipeline_id == pipeline.id
        assert lead.stage.code == "nouveau"
        assert lead.reference.startswith("LEAD-")


def test_create_lead_quick_with_catalog_lines_resolves_price(crm_setup) -> None:
    tenant, _pipeline, variant = crm_setup
    with use_tenant(tenant.id):
        lead = create_lead_quick(
            tenant=tenant,
            name="Opportunite Beta",
            lines=[{"variant_id": variant.id, "description": "T-Shirt", "qty": Decimal(10)}],
        )
        line = lead.lines.first()
        assert line.unit_price == Decimal("15000")
        assert line.subtotal == Decimal("150000.0000")


def test_add_lead_line_with_discount_computes_subtotal(crm_setup) -> None:
    tenant, _pipeline, variant = crm_setup
    with use_tenant(tenant.id):
        lead = create_lead_quick(tenant=tenant, name="Opportunite Gamma")
        line = add_lead_line(
            lead,
            variant_id=variant.id,
            description="T-Shirt",
            qty=Decimal(10),
            discount_pct=Decimal(10),
        )
        assert line.subtotal == Decimal("135000.0000")  # 10*15000*0.9


def test_custom_line_does_not_require_a_variant(crm_setup) -> None:
    tenant, _pipeline, _variant = crm_setup
    with use_tenant(tenant.id):
        lead = create_lead_quick(tenant=tenant, name="Opportunite Delta")
        line = add_lead_line(
            lead,
            description="Broderie personnalisee",
            qty=Decimal(1),
            unit_price=Decimal("5000"),
            is_custom=True,
        )
        assert line.is_custom
        assert CrmLeadLine.objects.filter(lead=lead, is_custom=True).count() == 1


def test_create_lead_without_any_pipeline_raises() -> None:
    tenant = Tenant.objects.create(code="CRM-EMPTY", name="CRM Empty Tenant")
    with use_tenant(tenant.id), pytest.raises(ValueError):
        create_lead_quick(tenant=tenant, name="Sans pipeline")
