from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkDefectType, StkLocation, StkWarehouse
from apps.stocks.services.defect_types import create_defect_type
from apps.stocks.services.warehouses import create_location, create_warehouse

pytestmark = pytest.mark.django_db


@pytest.fixture
def stocks_setup():
    tenant = Tenant.objects.create(code="STK-T", name="Stocks Tenant")
    with use_tenant(tenant.id):
        manager = User.objects.create_user(
            email="magasinier@example.com", password="Str0ngPassw0rd!23"
        )
        return tenant, manager


def test_create_warehouse(stocks_setup) -> None:
    tenant, manager = stocks_setup
    with use_tenant(tenant.id):
        warehouse = create_warehouse(
            tenant=tenant,
            code="WH-01",
            name="Entrepot principal",
            type=StkWarehouse.TYPE_PRINCIPAL,
            address="Zone industrielle Antananarivo",
            manager=manager,
        )
        assert warehouse.code == "WH-01"
        assert warehouse.type == StkWarehouse.TYPE_PRINCIPAL
        assert warehouse.manager_id == manager.id


def test_create_location_without_parent(stocks_setup) -> None:
    tenant, _manager = stocks_setup
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-01", name="Entrepot principal")
        location = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="A1",
            name="Rayon A1",
            type=StkLocation.TYPE_INTERNE,
        )
        assert location.parent is None
        assert location.warehouse_id == warehouse.id


def test_create_location_with_parent_in_same_warehouse(stocks_setup) -> None:
    tenant, _manager = stocks_setup
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-01", name="Entrepot principal")
        parent = create_location(tenant=tenant, warehouse=warehouse, code="A", name="Zone A")
        child = create_location(
            tenant=tenant, warehouse=warehouse, code="A1", name="Rayon A1", parent=parent
        )
        assert child.parent_id == parent.id
        assert parent.children.get(id=child.id) == child


def test_create_location_rejects_parent_in_different_warehouse(stocks_setup) -> None:
    tenant, _manager = stocks_setup
    with use_tenant(tenant.id):
        warehouse_a = create_warehouse(tenant=tenant, code="WH-A", name="Entrepot A")
        warehouse_b = create_warehouse(tenant=tenant, code="WH-B", name="Entrepot B")
        parent = create_location(tenant=tenant, warehouse=warehouse_a, code="A", name="Zone A")
        with pytest.raises(ValidationError):
            create_location(
                tenant=tenant,
                warehouse=warehouse_b,
                code="B1",
                name="Rayon B1",
                parent=parent,
            )


def test_location_tree_traversal(stocks_setup) -> None:
    tenant, _manager = stocks_setup
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-01", name="Entrepot principal")
        root = create_location(tenant=tenant, warehouse=warehouse, code="A", name="Zone A")
        child1 = create_location(
            tenant=tenant, warehouse=warehouse, code="A1", name="Rayon A1", parent=root
        )
        child2 = create_location(
            tenant=tenant, warehouse=warehouse, code="A2", name="Rayon A2", parent=root
        )
        assert set(root.children.values_list("id", flat=True)) == {child1.id, child2.id}
        assert child1.parent_id == root.id
        assert child2.parent_id == root.id


def test_create_location_refuses_a_third_level(stocks_setup) -> None:
    """Phase 3 §5.8 (sprint A2) : « dépôt -> zone -> emplacement, à trois
    niveaux au plus » — `StkWarehouse` (1) -> `StkLocation` racine, "zone"
    (2) -> `StkLocation` enfant, "emplacement" (3) est le maximum ; un
    petit-enfant (`Casier A1-1` sous `Rayon A1`, lui-même sous `Zone A`)
    constituerait un 4e niveau, refusé."""
    tenant, _manager = stocks_setup
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-01", name="Entrepot principal")
        root = create_location(tenant=tenant, warehouse=warehouse, code="A", name="Zone A")
        child1 = create_location(
            tenant=tenant, warehouse=warehouse, code="A1", name="Rayon A1", parent=root
        )
        with pytest.raises(ValidationError, match="trois niveaux"):
            create_location(
                tenant=tenant,
                warehouse=warehouse,
                code="A1-1",
                name="Casier A1-1",
                parent=child1,
            )


@pytest.mark.parametrize(
    "location_type",
    [
        StkLocation.TYPE_INTERNE,
        StkLocation.TYPE_FOURNISSEUR,
        StkLocation.TYPE_CLIENT,
        StkLocation.TYPE_PRODUCTION,
        StkLocation.TYPE_INVENTAIRE,
        StkLocation.TYPE_REBUT,
        StkLocation.TYPE_TRANSIT,
        StkLocation.TYPE_SOUS_TRAITANT,
    ],
)
def test_all_location_types_creatable(stocks_setup, location_type) -> None:
    tenant, _manager = stocks_setup
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-01", name="Entrepot principal")
        location = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code=f"LOC-{location_type}",
            name=f"Emplacement {location_type}",
            type=location_type,
        )
        assert location.type == location_type


def test_create_defect_type(stocks_setup) -> None:
    tenant, _manager = stocks_setup
    with use_tenant(tenant.id):
        defect_type = create_defect_type(
            tenant=tenant,
            code="DEF-01",
            name="Trou tissu",
            category=StkDefectType.CATEGORY_TISSU,
            severity=StkDefectType.SEVERITY_MAJEUR,
            default_action="Isoler et signaler au fournisseur",
        )
        assert defect_type.category == StkDefectType.CATEGORY_TISSU
        assert defect_type.severity == StkDefectType.SEVERITY_MAJEUR
