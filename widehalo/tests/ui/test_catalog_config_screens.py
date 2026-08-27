from __future__ import annotations

import uuid

import pytest
from apps.catalog.models import (
    Attribute,
    CatalogStandard,
    Category,
    PriceList,
    ProductTemplate,
    ProductVariant,
    UnitOfMeasure,
)
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def config_screens_setup():
    tenant = Tenant.objects.create(code="UI-CAT-CFG", name="UI Catalog Config Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="ui-cat-cfg@example.com", password="Str0ngPassw0rd!23"
        )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant


def test_config_index_renders(config_screens_setup) -> None:
    client, _tenant = config_screens_setup
    response = client.get("/catalog/config/")
    assert response.status_code == 200


def test_config_categories_create(config_screens_setup) -> None:
    client, tenant = config_screens_setup
    response = client.post("/catalog/config/categories/", {"name": "Textile"})
    assert response.status_code == 200
    assert b"Textile" in response.content
    with use_tenant(tenant.id):
        assert Category.objects.filter(name="Textile").exists()


def test_config_categories_with_parent(config_screens_setup) -> None:
    client, tenant = config_screens_setup
    with use_tenant(tenant.id):
        parent = Category.objects.create(tenant=tenant, name="Vetements")
    response = client.post(
        "/catalog/config/categories/", {"name": "T-Shirts", "parent_id": str(parent.id)}
    )
    assert response.status_code == 200
    with use_tenant(tenant.id):
        child = Category.objects.get(name="T-Shirts")
        assert child.parent_id == parent.id


def test_config_attributes_create_and_add_value(config_screens_setup) -> None:
    client, tenant = config_screens_setup
    response = client.post("/catalog/config/attributes/", {"name": "Couleur"})
    assert response.status_code == 200
    assert b"Couleur" in response.content
    with use_tenant(tenant.id):
        attribute = Attribute.objects.get(name="Couleur")

    response = client.post(
        "/catalog/config/attributes/",
        {"action": "add_value", "attribute_id": str(attribute.id), "value": "Rouge"},
    )
    assert response.status_code == 200
    assert b"Rouge" in response.content
    with use_tenant(tenant.id):
        assert attribute.values.filter(value="Rouge").exists()


def test_config_uom_create_and_conversion(config_screens_setup) -> None:
    client, tenant = config_screens_setup
    response = client.post(
        "/catalog/config/units/",
        {"code": "KG", "name": "Kilogramme", "category": UnitOfMeasure.CATEGORY_WEIGHT},
    )
    assert response.status_code == 200
    assert b"KG" in response.content

    response = client.post(
        "/catalog/config/units/",
        {"code": "G", "name": "Gramme", "category": UnitOfMeasure.CATEGORY_WEIGHT},
    )
    assert response.status_code == 200

    with use_tenant(tenant.id):
        kg = UnitOfMeasure.objects.get(code="KG")
        g = UnitOfMeasure.objects.get(code="G")

    response = client.post(
        "/catalog/config/units/",
        {
            "action": "add_conversion",
            "from_unit_id": str(kg.id),
            "to_unit_id": str(g.id),
            "factor": "1000",
        },
    )
    assert response.status_code == 200
    assert b"1000" in response.content


def test_config_price_lists_create_and_detail(config_screens_setup) -> None:
    client, tenant = config_screens_setup
    with use_tenant(tenant.id):
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PC", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )
        template = ProductTemplate.objects.create(tenant=tenant, name="Gamme", base_uom=uom)
        variant = ProductVariant.objects.create(tenant=tenant, template=template)

    response = client.post(
        "/catalog/config/price-lists/",
        {"name": "Liste standard", "kind": PriceList.KIND_DEFAULT},
    )
    assert response.status_code == 200
    assert b"Liste standard" in response.content
    with use_tenant(tenant.id):
        price_list = PriceList.objects.get(name="Liste standard")

    detail_url = f"/catalog/config/price-lists/{price_list.id}/"
    response = client.get(detail_url)
    assert response.status_code == 200

    response = client.post(detail_url, {"variant_id": str(variant.id), "price_mga": "3000"})
    assert response.status_code == 302
    with use_tenant(tenant.id):
        assert price_list.items.filter(variant=variant, price_mga="3000").exists()


def test_config_packaging_create(config_screens_setup) -> None:
    client, tenant = config_screens_setup
    with use_tenant(tenant.id):
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PC", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )
        template = ProductTemplate.objects.create(tenant=tenant, name="Gamme", base_uom=uom)
        variant = ProductVariant.objects.create(tenant=tenant, template=template)

    response = client.post(
        "/catalog/config/packaging/",
        {
            "variant_id": str(variant.id),
            "unit_count": "12",
            "uom_id": str(uom.id),
            "barcode": "1234567890123",
        },
    )
    assert response.status_code == 200
    assert b"1234567890123" in response.content


def test_config_standards_create(config_screens_setup) -> None:
    client, tenant = config_screens_setup
    response = client.post(
        "/catalog/config/standards/",
        {"code": "OEKO-100", "name": "OEKO-TEX Standard 100", "description": "..."},
    )
    assert response.status_code == 200
    assert b"OEKO-100" in response.content
    with use_tenant(tenant.id):
        assert CatalogStandard.objects.filter(code="OEKO-100").exists()


def test_config_certifications_create(config_screens_setup) -> None:
    client, tenant = config_screens_setup
    with use_tenant(tenant.id):
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PC", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )
        template = ProductTemplate.objects.create(tenant=tenant, name="Gamme", base_uom=uom)
        variant = ProductVariant.objects.create(tenant=tenant, template=template)
        standard = CatalogStandard.objects.create(tenant=tenant, code="GOTS", name="GOTS")

    response = client.post(
        "/catalog/config/certifications/",
        {
            "variant_id": str(variant.id),
            "standard_id": str(standard.id),
            "partner_id": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 200
    assert b"GOTS" in response.content
