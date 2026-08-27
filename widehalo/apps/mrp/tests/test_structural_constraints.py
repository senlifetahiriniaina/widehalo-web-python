"""T2 (couches 4-5 du CDC, §8) : contraintes structurelles/d'interdependance
au niveau base pour `mrp` — la detection de cycle de nomenclature
(RG-MRP anti-cycle) est deja couverte par `test_bom.py` et n'est pas
reproduite ici. Ce fichier comble le reste : comportement `on_delete`
(PROTECT/CASCADE/SET_NULL) de chaque FK du modele, en particulier les
PROTECT contre suppression avec enregistrements dependants explicitement
signales comme sous-testes (`MrpOrderComponent.bom_line`,
`MrpOrder.bom`/`workshop`).

RLS (isolation tenant) est hors-perimetre (couverte ailleurs)."""

from __future__ import annotations

import pytest
from django.db.models.deletion import ProtectedError

from apps.core.tests.factories import TenantFactory, UserFactory
from apps.core.tests.utils import use_tenant
from apps.mrp.models import MrpBomLineState, MrpOrderComponent, MrpSubcontractOrder, MrpWorkOrder
from apps.mrp.tests.factories import (
    MrpBomFactory,
    MrpBomLineFactory,
    MrpBomLineStateFactory,
    MrpCraFactory,
    MrpCriFactory,
    MrpOperationFactory,
    MrpOrderComponentFactory,
    MrpOrderFactory,
    MrpRoutingFactory,
    MrpRoutingStepFactory,
    MrpScrapFactory,
    MrpSubcontractOrderFactory,
    MrpWorkcenterFactory,
    MrpWorkOrderFactory,
    MrpWorkshopFactory,
)

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------
# on_delete=PROTECT — signale comme sous-teste dans le plan de durcissement
# --------------------------------------------------------------------------


def test_bom_line_cannot_be_deleted_while_referenced_by_an_order_component() -> None:
    """`MrpOrderComponent.bom_line` est PROTECT : un composant deja
    materialise sur un ordre bloque la suppression de la ligne de
    nomenclature d'origine."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        component = MrpOrderComponentFactory(tenant=tenant)
        bom_line = component.bom_line

        with pytest.raises(ProtectedError):
            bom_line.delete()


def test_bom_cannot_be_deleted_while_referenced_by_an_order() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        order = MrpOrderFactory(tenant=tenant)
        bom = order.bom

        with pytest.raises(ProtectedError):
            bom.delete()


def test_workshop_cannot_be_deleted_while_referenced_by_an_order() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        order = MrpOrderFactory(tenant=tenant)
        workshop = order.workshop

        with pytest.raises(ProtectedError):
            workshop.delete()


def test_operation_cannot_be_deleted_while_referenced_by_a_routing_step() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        step = MrpRoutingStepFactory(tenant=tenant)
        operation = step.operation

        with pytest.raises(ProtectedError):
            operation.delete()


def test_workcenter_cannot_be_deleted_while_referenced_by_a_routing_step() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        step = MrpRoutingStepFactory(tenant=tenant)
        workcenter = step.workcenter

        with pytest.raises(ProtectedError):
            workcenter.delete()


def test_workcenter_cannot_be_deleted_while_referenced_by_a_work_order() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        work_order = MrpWorkOrderFactory(tenant=tenant)
        workcenter = work_order.workcenter

        with pytest.raises(ProtectedError):
            workcenter.delete()


def test_workshop_cannot_be_deleted_while_referenced_by_a_cra() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        cra = MrpCraFactory(tenant=tenant)
        workshop = cra.workshop

        with pytest.raises(ProtectedError):
            workshop.delete()


def test_employee_cannot_be_deleted_while_referenced_by_a_cra() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        cra = MrpCraFactory(tenant=tenant)
        employee = cra.employee

        with pytest.raises(ProtectedError):
            employee.delete()


def test_workcenter_cannot_be_deleted_while_referenced_by_a_cri() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        cri = MrpCriFactory(tenant=tenant)
        workcenter = cri.workcenter

        with pytest.raises(ProtectedError):
            workcenter.delete()


def test_declaring_user_cannot_be_deleted_while_referenced_by_a_scrap() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        scrap = MrpScrapFactory(tenant=tenant)
        declared_by = scrap.declared_by

        with pytest.raises(ProtectedError):
            declared_by.delete()


# --------------------------------------------------------------------------
# on_delete=CASCADE
# --------------------------------------------------------------------------


def test_workshop_with_only_workcenters_and_no_order_can_be_deleted() -> None:
    """`MrpWorkcenter.workshop` est CASCADE (a la difference de
    `MrpOrder.workshop`, PROTECT) : sans ordre rattache, supprimer un
    atelier entraine la suppression de ses postes de charge."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        workcenter = MrpWorkcenterFactory(tenant=tenant)
        workshop = workcenter.workshop
        workcenter_id = workcenter.id

        workshop.delete()

        from apps.mrp.models import MrpWorkcenter

        assert not MrpWorkcenter.objects.filter(pk=workcenter_id).exists()


def test_deleting_a_routing_cascades_to_its_steps() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        step = MrpRoutingStepFactory(tenant=tenant)
        routing = step.routing
        step_id = step.id

        routing.delete()

        from apps.mrp.models import MrpRoutingStep

        assert not MrpRoutingStep.objects.filter(pk=step_id).exists()


def test_deleting_a_bom_cascades_to_its_lines() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        line = MrpBomLineFactory(tenant=tenant)
        bom = line.bom
        line_id = line.id

        bom.delete()

        from apps.mrp.models import MrpBomLine

        assert not MrpBomLine.objects.filter(pk=line_id).exists()


def test_deleting_an_order_cascades_to_its_components() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        component = MrpOrderComponentFactory(tenant=tenant)
        order = component.order
        component_id = component.id

        order.delete()

        assert not MrpOrderComponent.objects.filter(pk=component_id).exists()


def test_deleting_an_order_cascades_to_its_work_orders() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        work_order = MrpWorkOrderFactory(tenant=tenant)
        order = work_order.order
        work_order_id = work_order.id

        order.delete()

        assert not MrpWorkOrder.objects.filter(pk=work_order_id).exists()


def test_deleting_an_order_cascades_to_its_subcontract_orders() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        subcontract = MrpSubcontractOrderFactory(tenant=tenant)
        order = subcontract.order
        subcontract_id = subcontract.id

        order.delete()

        assert not MrpSubcontractOrder.objects.filter(pk=subcontract_id).exists()


def test_deleting_an_order_component_cascades_to_its_procurement_state() -> None:
    """`MrpBomLineState.order_component` est un OneToOne CASCADE."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        state = MrpBomLineStateFactory(tenant=tenant)
        component = state.order_component
        state_id = state.id

        component.delete()

        assert not MrpBomLineState.objects.filter(pk=state_id).exists()


def test_deleting_a_workcenter_cascades_to_its_maintenance_plans() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        from apps.mrp.tests.factories import MrpMaintenancePlanFactory

        plan = MrpMaintenancePlanFactory(tenant=tenant)
        workcenter = plan.workcenter
        plan_id = plan.id

        workcenter.delete()

        from apps.mrp.models import MrpMaintenancePlan

        assert not MrpMaintenancePlan.objects.filter(pk=plan_id).exists()


# --------------------------------------------------------------------------
# on_delete=SET_NULL
# --------------------------------------------------------------------------


def test_deleting_a_routing_nullifies_the_bom() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        routing = MrpRoutingFactory(tenant=tenant)
        bom = MrpBomFactory(tenant=tenant, routing=routing)

        routing.delete()
        bom.refresh_from_db()

        assert bom.routing_id is None


def test_deleting_a_parent_bom_nullifies_the_version() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        parent_bom = MrpBomFactory(tenant=tenant)
        version = MrpBomFactory(tenant=tenant, parent_bom=parent_bom)

        parent_bom.delete()
        version.refresh_from_db()

        assert version.parent_bom_id is None


def test_deleting_a_routing_nullifies_the_order() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        routing = MrpRoutingFactory(tenant=tenant)
        order = MrpOrderFactory(tenant=tenant, routing=routing)

        routing.delete()
        order.refresh_from_db()

        assert order.routing_id is None


def test_deleting_a_routing_step_nullifies_the_work_order() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        step = MrpRoutingStepFactory(tenant=tenant)
        work_order = MrpWorkOrderFactory(tenant=tenant, routing_step=step)

        step.delete()
        work_order.refresh_from_db()

        assert work_order.routing_step_id is None


def test_deleting_an_operation_nullifies_the_optional_bom_line_operation() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        operation = MrpOperationFactory(tenant=tenant)
        line = MrpBomLineFactory(tenant=tenant, operation=operation)

        operation.delete()
        line.refresh_from_db()

        assert line.operation_id is None


def test_deleting_a_manager_nullifies_the_workshop() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        manager = UserFactory()
        workshop = MrpWorkshopFactory(tenant=tenant, manager=manager)

        manager.delete()
        workshop.refresh_from_db()

        assert workshop.manager_id is None
