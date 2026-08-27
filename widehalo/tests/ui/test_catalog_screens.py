from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from apps.catalog.models import (
    Attribute,
    AttributeValue,
    PriceList,
    PriceListItem,
    ProductTemplate,
    UnitOfMeasure,
)
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def catalog_screens_setup():
    tenant = Tenant.objects.create(code="UI-CAT", name="UI Catalog Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="ui-cat@example.com", password="Str0ngPassw0rd!23")
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PC", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )
        template = ProductTemplate.objects.create(
            tenant=tenant,
            name="T-Shirt",
            base_uom=uom,
            reference="TPL-0001",
            base_price_mga=Decimal("5000"),
        )
        color = Attribute.objects.create(tenant=tenant, name="Couleur")
        AttributeValue.objects.create(tenant=tenant, attribute=color, value="Rouge")
        AttributeValue.objects.create(tenant=tenant, attribute=color, value="Bleu")

    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, template, color


def test_template_list_renders(catalog_screens_setup) -> None:
    client, *_ = catalog_screens_setup
    response = client.get("/catalog/templates/")
    assert response.status_code == 200


def test_template_detail_renders(catalog_screens_setup) -> None:
    client, _tenant, template, _color = catalog_screens_setup
    response = client.get(f"/catalog/templates/{template.id}/")
    assert response.status_code == 200
    assert b"T-Shirt" in response.content


def test_generate_variants_creates_variants(catalog_screens_setup) -> None:
    client, tenant, template, color = catalog_screens_setup
    response = client.post(
        f"/catalog/templates/{template.id}/",
        {"action": "generate_variants", "attribute_ids": [str(color.id)]},
    )
    assert response.status_code == 302
    with use_tenant(tenant.id):
        assert template.variants.count() == 2


def test_generate_variants_rejects_more_than_two_attributes(catalog_screens_setup) -> None:
    client, tenant, template, color = catalog_screens_setup
    with use_tenant(tenant.id):
        size = Attribute.objects.create(tenant=tenant, name="Taille")
        material = Attribute.objects.create(tenant=tenant, name="Matiere")
    response = client.post(
        f"/catalog/templates/{template.id}/",
        {
            "action": "generate_variants",
            "attribute_ids": [str(color.id), str(size.id), str(material.id)],
        },
    )
    assert response.status_code == 200
    assert b"maximum" in response.content or response.context["error"]


def test_generate_variants_rejects_over_fifty_combinations(catalog_screens_setup) -> None:
    client, tenant, template, color = catalog_screens_setup
    with use_tenant(tenant.id):
        size = Attribute.objects.create(tenant=tenant, name="Taille")
        for i in range(8):
            AttributeValue.objects.create(tenant=tenant, attribute=color, value=f"couleur-{i}")
        for i in range(7):
            AttributeValue.objects.create(tenant=tenant, attribute=size, value=f"taille-{i}")
    response = client.post(
        f"/catalog/templates/{template.id}/",
        {"action": "generate_variants", "attribute_ids": [str(color.id), str(size.id)]},
    )
    assert response.status_code == 200
    assert response.context["error"]
    with use_tenant(tenant.id):
        assert template.variants.count() == 0


def test_add_supplier_info(catalog_screens_setup) -> None:
    client, tenant, template, color = catalog_screens_setup
    client.post(
        f"/catalog/templates/{template.id}/",
        {"action": "generate_variants", "attribute_ids": [str(color.id)]},
    )
    with use_tenant(tenant.id):
        variant = template.variants.first()
    response = client.post(
        f"/catalog/templates/{template.id}/",
        {
            "action": "add_supplier_info",
            "variant_id": str(variant.id),
            "partner_id": str(uuid.uuid4()),
            "supplier_reference": "SUP-1",
            "price_mga": "4200",
            "lead_time_days": "5",
        },
    )
    assert response.status_code == 302
    with use_tenant(tenant.id):
        assert variant.supplier_infos.count() == 1


def test_template_detail_shows_price_cascade(catalog_screens_setup) -> None:
    client, tenant, template, color = catalog_screens_setup
    client.post(
        f"/catalog/templates/{template.id}/",
        {"action": "generate_variants", "attribute_ids": [str(color.id)]},
    )
    with use_tenant(tenant.id):
        variant = template.variants.first()
        price_list = PriceList.objects.create(
            tenant=tenant, name="Liste par defaut", kind=PriceList.KIND_DEFAULT
        )
        PriceListItem.objects.create(
            tenant=tenant, price_list=price_list, variant=variant, price_mga=Decimal("4800")
        )
    response = client.get(f"/catalog/templates/{template.id}/")
    assert response.status_code == 200
    assert b"4800" in response.content


def test_textile_converter_weight_to_length(catalog_screens_setup) -> None:
    client, *_ = catalog_screens_setup
    response = client.get("/catalog/textile-converter/")
    assert response.status_code == 200

    response = client.post(
        "/catalog/textile-converter/",
        {
            "direction": "weight_to_length",
            "weight_kg": "1",
            "weight_gsm": "200",
            "width_cm": "150",
        },
    )
    assert response.status_code == 200
    assert response.context["error"] is None
    assert response.context["result"] is not None


def test_textile_converter_length_to_weight(catalog_screens_setup) -> None:
    client, *_ = catalog_screens_setup
    response = client.post(
        "/catalog/textile-converter/",
        {
            "direction": "length_to_weight",
            "length_m": "10",
            "weight_gsm": "200",
            "width_cm": "150",
        },
    )
    assert response.status_code == 200
    assert response.context["error"] is None
    assert response.context["result"] is not None
