from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from apps.catalog.tests.factories import ProductTemplateFactory, ProductVariantFactory
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.feasibility.services.simulation import (
    add_study_line,
    compute_margin_pct,
    create_study,
    resolve_unit_price,
    simulate_study_line,
)
from apps.feasibility.tests.factories import FeaStudyFactory, FeaStudyLineFactory
from apps.mrp.models import MrpOrder
from apps.mrp.services.bom import activate_bom, add_bom_line

pytestmark = pytest.mark.django_db


def test_create_study_assigns_reference() -> None:
    tenant = Tenant.objects.create(code="FEA-T1", name="Feasibility Tenant 1")
    with use_tenant(tenant.id):
        study = create_study(tenant, name="Sac a main en cuir vegetal")
        assert study.reference
        assert study.status == study.STATUS_DRAFT


def test_simulate_study_line_with_manual_cost_breakdown_and_price() -> None:
    """Etude 100% exploratoire (aucune variante/BOM reelle) : la simulation
    doit se contenter du `cost_breakdown` et du prix saisis manuellement,
    jamais lever d'exception faute de BOM/variante."""
    tenant = Tenant.objects.create(code="FEA-T2", name="Feasibility Tenant 2")
    with use_tenant(tenant.id):
        study = FeaStudyFactory(tenant=tenant)
        line = add_study_line(
            study,
            hypothetical_spec={"name": "Sac hypothese"},
            assumed_qty=Decimal(20),
            assumed_unit_price_mga=Decimal(8000),
            cost_breakdown={
                "material": Decimal(3000),
                "labor": Decimal(1000),
                "overhead": Decimal(200),
                "total": Decimal(4200),
            },
        )

        orders_before = MrpOrder.objects.count()
        simulate_study_line(line)
        line.refresh_from_db()

        assert MrpOrder.objects.count() == orders_before
        assert line.cost_breakdown["total"] == "4200"
        assert line.assumed_unit_price_mga == Decimal(8000)
        # (20*8000 - 4200) / (20*8000) * 100 = (160000-4200)/160000*100
        assert line.computed_margin_pct == compute_margin_pct(
            total_revenue_mga=Decimal(160000), total_cost_mga=Decimal(4200)
        )


def test_simulate_study_line_uses_real_bom_when_variant_and_bom_exist() -> None:
    """Une variante catalogue reelle avec une BOM active DOIT faire passer
    la simulation par `mrp.services.public.simulate_bom_cost` (jamais le
    `cost_breakdown` manuel dans ce cas)."""
    tenant = Tenant.objects.create(code="FEA-T3", name="Feasibility Tenant 3")
    with use_tenant(tenant.id):
        template = ProductTemplateFactory(tenant=tenant, base_price_mga=Decimal("2500"))
        variant = ProductVariantFactory(tenant=tenant, template=template)

        from apps.mrp.tests.factories import MrpBomFactory

        component_id = uuid.uuid4()
        bom = MrpBomFactory(tenant=tenant, product_template_id=template.id, qty=Decimal(1))
        add_bom_line(bom, component_template_id=component_id, qty=Decimal(2))
        activate_bom(bom)

        study = FeaStudyFactory(tenant=tenant)
        line = add_study_line(
            study,
            variant_id=variant.id,
            assumed_qty=Decimal(10),
            assumed_unit_price_mga=Decimal(0),
        )

        orders_before = MrpOrder.objects.count()
        simulate_study_line(
            line, component_unit_costs={component_id: Decimal(300)}, overhead_rate_pct=Decimal(10)
        )
        line.refresh_from_db()

        assert MrpOrder.objects.count() == orders_before
        # explode(): 2 (ligne) * 10 (qty) = 20, * 300 = 6000 de matiere
        # (Decimal issu de champs `decimal_places=4`, d'ou le format).
        assert Decimal(line.cost_breakdown["material"]) == Decimal(6000)
        assert Decimal(line.cost_breakdown["labor"]) == Decimal(0)
        assert Decimal(line.cost_breakdown["total"]) == Decimal(6000)
        # Aucun prix hypothese saisi (0) + variante reelle -> prix catalogue
        # (base_price_mga=2500, aucune PriceList) repris tel quel.
        assert line.assumed_unit_price_mga == Decimal("2500")
        # revenu = 10*2500=25000, marge = (25000-6000)/25000*100 = 76.0
        assert line.computed_margin_pct == Decimal("76.00")


def test_resolve_unit_price_prefers_manual_price_over_catalog() -> None:
    """Un prix hypothetique explicitement saisi (non nul) prime toujours
    sur le prix catalogue courant, meme sur une variante reelle — cf.
    docstring `resolve_unit_price`."""
    tenant = Tenant.objects.create(code="FEA-T4", name="Feasibility Tenant 4")
    with use_tenant(tenant.id):
        template = ProductTemplateFactory(tenant=tenant, base_price_mga=Decimal("2500"))
        variant = ProductVariantFactory(tenant=tenant, template=template)
        line = FeaStudyLineFactory(
            tenant=tenant, variant_id=variant.id, assumed_unit_price_mga=Decimal(9999)
        )
        assert resolve_unit_price(line) == Decimal(9999)


def test_compute_margin_pct_returns_zero_when_no_revenue() -> None:
    assert compute_margin_pct(total_revenue_mga=Decimal(0), total_cost_mga=Decimal(500)) == Decimal(
        0
    )
