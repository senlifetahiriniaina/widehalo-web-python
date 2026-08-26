from __future__ import annotations

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.mrp.models import MrpOperation, MrpRouting, MrpRoutingStep, MrpWorkcenter, MrpWorkshop

pytestmark = pytest.mark.django_db


@pytest.fixture
def mrp_setup():
    tenant = Tenant.objects.create(code="MRP-T", name="MRP Tenant")
    with use_tenant(tenant.id):
        return tenant


def test_create_workshop_and_workcenter(mrp_setup) -> None:
    tenant = mrp_setup
    with use_tenant(tenant.id):
        workshop = MrpWorkshop.objects.create(tenant=tenant, code="ATL-1", name="Atelier Coupe")
        workcenter = MrpWorkcenter.objects.create(
            tenant=tenant,
            workshop=workshop,
            code="COUPE-1",
            name="Table de coupe 1",
            type=MrpWorkcenter.TYPE_CUTTING,
            cost_per_hour_mga="5000",
        )
        assert workcenter.workshop_id == workshop.id
        assert workshop.workcenters.count() == 1


def test_subcontractor_workshop_flags(mrp_setup) -> None:
    tenant = mrp_setup
    with use_tenant(tenant.id):
        workshop = MrpWorkshop.objects.create(
            tenant=tenant, code="SOUS-1", name="Sous-traitant Broderie", is_subcontractor=True
        )
        assert workshop.is_subcontractor


def test_routing_with_ordered_steps(mrp_setup) -> None:
    tenant = mrp_setup
    with use_tenant(tenant.id):
        workshop = MrpWorkshop.objects.create(tenant=tenant, code="ATL-1", name="Atelier")
        workcenter = MrpWorkcenter.objects.create(
            tenant=tenant,
            workshop=workshop,
            code="C1",
            name="Coupe",
            type=MrpWorkcenter.TYPE_CUTTING,
        )
        operation = MrpOperation.objects.create(
            tenant=tenant,
            code="OP-COUPE",
            name="Decoupe tissu",
            workcenter_type=MrpWorkcenter.TYPE_CUTTING,
        )
        routing = MrpRouting.objects.create(tenant=tenant, code="RTG-1", name="Gamme chemise")
        MrpRoutingStep.objects.create(
            tenant=tenant,
            routing=routing,
            sequence=2,
            operation=operation,
            workcenter=workcenter,
            duration_min=15,
        )
        MrpRoutingStep.objects.create(
            tenant=tenant,
            routing=routing,
            sequence=1,
            operation=operation,
            workcenter=workcenter,
            duration_min=10,
        )
        steps = list(routing.steps.all())
        assert [s.sequence for s in steps] == [1, 2]
