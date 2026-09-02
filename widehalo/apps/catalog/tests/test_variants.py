from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.catalog.models import Attribute, AttributeValue, ProductTemplate, UnitOfMeasure
from apps.catalog.services.variants import (
    MAX_VARIANT_GENERATING_ATTRIBUTES,
    generate_variants,
    set_variant_attributes,
)
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def template_with_attributes():
    tenant = Tenant.objects.create(code="CAT-VAR", name="Catalog Variants Tenant")
    with use_tenant(tenant.id):
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PC", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )
        template = ProductTemplate.objects.create(
            tenant=tenant, name="T-Shirt", base_uom=uom, reference="TPL-0001"
        )
        color = Attribute.objects.create(tenant=tenant, name="Couleur")
        size = Attribute.objects.create(tenant=tenant, name="Taille")
        return tenant, template, color, size


def test_more_than_two_variant_attributes_is_rejected(template_with_attributes) -> None:
    tenant, template, color, size = template_with_attributes
    with use_tenant(tenant.id):
        material = Attribute.objects.create(tenant=tenant, name="Matiere")
        with pytest.raises(ValidationError):
            set_variant_attributes(template, [color.id, size.id, material.id])


def test_two_variant_attributes_is_accepted(template_with_attributes) -> None:
    tenant, template, color, size = template_with_attributes
    with use_tenant(tenant.id):
        set_variant_attributes(template, [color.id, size.id])
        assert template.variant_attributes.count() == MAX_VARIANT_GENERATING_ATTRIBUTES


def test_8x6_style_generates_48_skus_with_unique_ean13(template_with_attributes) -> None:
    """Critere d'acceptation T1 du cahier des charges refonte UX ("creer
    un style 8 tailles × 6 couleurs genere 48 SKU") + code-barres EAN-13
    genere automatiquement par variante (Sprint 4 / L3, cf.
    docs/planning/2026-refonte-ux-sprints.md §5)."""
    tenant, template, color, size = template_with_attributes
    with use_tenant(tenant.id):
        for i in range(6):
            AttributeValue.objects.create(tenant=tenant, attribute=color, value=f"couleur-{i}")
        for i in range(8):
            AttributeValue.objects.create(tenant=tenant, attribute=size, value=f"taille-{i}")
        set_variant_attributes(template, [color.id, size.id])

        variants = generate_variants(template)

        assert len(variants) == 48
        assert template.variants.count() == 48
        ean_codes = {v.ean13 for v in variants}
        assert len(ean_codes) == 48
        assert all(len(code) == 13 and code.isdigit() for code in ean_codes)


def test_56_combinations_are_rejected(template_with_attributes) -> None:
    tenant, template, color, size = template_with_attributes
    with use_tenant(tenant.id):
        for i in range(8):
            AttributeValue.objects.create(tenant=tenant, attribute=color, value=f"couleur-{i}")
        for i in range(7):
            AttributeValue.objects.create(tenant=tenant, attribute=size, value=f"taille-{i}")
        set_variant_attributes(template, [color.id, size.id])

        with pytest.raises(ValidationError):
            generate_variants(template)


def test_50_combinations_are_accepted(template_with_attributes) -> None:
    tenant, template, color, size = template_with_attributes
    with use_tenant(tenant.id):
        for i in range(10):
            AttributeValue.objects.create(tenant=tenant, attribute=color, value=f"couleur-{i}")
        for i in range(5):
            AttributeValue.objects.create(tenant=tenant, attribute=size, value=f"taille-{i}")
        set_variant_attributes(template, [color.id, size.id])

        variants = generate_variants(template)
        assert len(variants) == 50
