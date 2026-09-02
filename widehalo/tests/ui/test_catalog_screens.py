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


def test_template_list_shows_category_column(catalog_screens_setup) -> None:
    from apps.catalog.models import Category

    client, tenant, template, _color = catalog_screens_setup
    with use_tenant(tenant.id):
        family = Category.objects.create(tenant=tenant, name="Vetements")
        subfamily = Category.objects.create(tenant=tenant, name="Hauts", parent=family)
        template.category = subfamily
        template.save(update_fields=["category"])

    response = client.get("/catalog/templates/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Catégorie" in body
    assert "Hauts" in body


def test_template_detail_renders(catalog_screens_setup) -> None:
    client, _tenant, template, _color = catalog_screens_setup
    response = client.get(f"/catalog/templates/{template.id}/")
    assert response.status_code == 200
    assert b"T-Shirt" in response.content


def test_template_detail_sellable_toggle_button(catalog_screens_setup) -> None:
    """Bouton bascule (pas une case a cocher, cf. demande explicite) pour
    indiquer si le produit est vendable — un vrai bouton `<button>` qui
    POST son etat inverse au clic, jamais un `<input type="checkbox">`."""
    client, tenant, template, _color = catalog_screens_setup
    assert template.is_sellable is True

    response = client.get(f"/catalog/templates/{template.id}/")
    assert b'class="toggle-btn is-on"' in response.content
    assert b"Vendable" in response.content

    response = client.post(f"/catalog/templates/{template.id}/", {"action": "toggle_sellable"})
    assert response.status_code == 302
    template.refresh_from_db()
    assert template.is_sellable is False

    response = client.get(f"/catalog/templates/{template.id}/")
    assert b"Non vendable" in response.content
    assert b'class="toggle-btn is-on"' not in response.content


def test_template_detail_shows_size_color_matrix_after_generation(
    catalog_screens_setup,
) -> None:
    """Grille tailles×couleurs (T1 refonte UX, Sprint 4 / L3, cf.
    docs/planning/2026-refonte-ux-sprints.md §5) : absente tant qu'aucune
    variante n'est generee, presente (avec les valeurs en tetes de ligne/
    colonne) une fois 2 attributs generateurs fixes."""
    from apps.catalog.services.variants import generate_variants, set_variant_attributes

    client, tenant, template, color = catalog_screens_setup

    response = client.get(f"/catalog/templates/{template.id}/")
    assert b"variant-matrix" not in response.content

    with use_tenant(tenant.id):
        size = Attribute.objects.create(tenant=tenant, name="Taille")
        AttributeValue.objects.create(tenant=tenant, attribute=size, value="S")
        AttributeValue.objects.create(tenant=tenant, attribute=size, value="M")
        set_variant_attributes(template, [color.id, size.id])
        generate_variants(template)

    response = client.get(f"/catalog/templates/{template.id}/")
    body = response.content.decode()
    assert "variant-matrix" in body
    assert "Rouge" in body
    assert "Bleu" in body
    assert ">S<" in body
    assert ">M<" in body


def test_template_create_requires_a_subfamily(catalog_screens_setup) -> None:
    """Chaque produit doit etre classe dans une sous-famille (categorie
    ENFANT, cf. `Category.parent`) — jamais directement sous une famille
    racine ni sans categorie du tout."""
    from apps.catalog.models import Category

    client, tenant, template, _color = catalog_screens_setup

    response = client.get("/catalog/templates/new/")
    assert response.status_code == 200
    # Aucune sous-famille n'existe encore dans le fixture (seul le
    # template lui-meme est cree, sans categorie) — le message d'avertissement
    # doit s'afficher.
    assert b"sous-famille" in response.content.lower()

    with use_tenant(tenant.id):
        family = Category.objects.create(tenant=tenant, name="Vetements")
        subfamily = Category.objects.create(tenant=tenant, name="Hauts", parent=family)

    response = client.post(
        "/catalog/templates/new/",
        {
            "name": "Polo technique",
            "category_id": str(subfamily.id),
            "base_uom_id": str(template.base_uom_id),
            "base_price_mga": "15000",
            "is_sellable": "on",
        },
    )
    assert response.status_code == 302
    with use_tenant(tenant.id):
        created = ProductTemplate.objects.get(tenant=tenant, name="Polo technique")
        assert created.category_id == subfamily.id
        assert created.category.parent_id == family.id
        assert created.is_sellable is True


def test_template_create_rejects_root_category(catalog_screens_setup) -> None:
    """Une categorie racine (sans parent, donc une FAMILLE et non une
    sous-famille) ne doit jamais etre proposee par le selecteur."""
    from apps.catalog.models import Category

    client, tenant, template, _color = catalog_screens_setup
    with use_tenant(tenant.id):
        root = Category.objects.create(tenant=tenant, name="Famille racine")

    response = client.get("/catalog/templates/new/")
    assert b"Famille racine" not in response.content

    response = client.post(
        "/catalog/templates/new/",
        {
            "name": "Produit invalide",
            "category_id": str(root.id),
            "base_uom_id": str(template.base_uom_id),
        },
    )
    assert response.status_code == 200
    assert b"introuvable" in response.content.lower()


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


def test_template_detail_price_is_formatted_with_thousands_separator(
    catalog_screens_setup,
) -> None:
    client, tenant, template, _color = catalog_screens_setup
    with use_tenant(tenant.id):
        template.base_price_mga = Decimal("98610.0000")
        template.save(update_fields=["base_price_mga"])
    response = client.get(f"/catalog/templates/{template.id}/")
    assert response.status_code == 200
    assert "98\xa0610,00\xa0MGA" in response.content.decode()


def test_generate_variants_fieldset_has_form_field_spacing_class(
    catalog_screens_setup,
) -> None:
    client, _tenant, template, _color = catalog_screens_setup
    response = client.get(f"/catalog/templates/{template.id}/")
    body = response.content.decode()
    assert '<fieldset class="form-field">' in body


def test_add_supplier_info_form_uses_partner_picker_not_free_text(
    catalog_screens_setup,
) -> None:
    client, _tenant, template, _color = catalog_screens_setup
    response = client.get(f"/catalog/templates/{template.id}/")
    body = response.content.decode()
    assert '<input id="partner_id" type="text" name="partner_id" required>' not in body
    assert 'id="partner-picker-search-partner_id"' in body
    assert "+ Nouveau partenaire" in body


def test_add_supplier_info_error_preserves_form_values(catalog_screens_setup) -> None:
    client, tenant, template, color = catalog_screens_setup
    client.post(
        f"/catalog/templates/{template.id}/",
        {"action": "generate_variants", "attribute_ids": [str(color.id)]},
    )
    partner_id = str(uuid.uuid4())
    response = client.post(
        f"/catalog/templates/{template.id}/",
        {
            "action": "add_supplier_info",
            "variant_id": str(uuid.uuid4()),  # variante inexistante -> erreur
            "partner_id": partner_id,
            "supplier_reference": "SUP-KEEP",
            "price_mga": "4200",
            "lead_time_days": "5",
        },
    )
    assert response.status_code == 200
    assert response.context["error"]
    body = response.content.decode()
    assert partner_id in body
    assert 'value="SUP-KEEP"' in body
    assert 'value="4200"' in body
    assert 'value="5"' in body


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
    assert "4\xa0800,00\xa0MGA" in response.content.decode()


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
