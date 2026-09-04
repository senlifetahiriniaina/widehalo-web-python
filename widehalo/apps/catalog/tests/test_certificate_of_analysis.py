"""Bloc D, D2 (QUA-8) : `requires_certificate_of_analysis` — même patron
exact qu'`is_variant_sellable` (test_sellable.py), champ porté par
`ProductTemplate`, résolu depuis un `variant_id`."""

from __future__ import annotations

import uuid

import pytest

from apps.catalog.models import ProductTemplate, ProductVariant, UnitOfMeasure
from apps.catalog.services.public import requires_certificate_of_analysis
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def certificate_setup():
    tenant = Tenant.objects.create(code="CAT-COA", name="Certificate Tenant")
    with use_tenant(tenant.id):
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="KG", name="Kilogramme", category=UnitOfMeasure.CATEGORY_WEIGHT
        )
        regulated_template = ProductTemplate.objects.create(
            tenant=tenant,
            name="Lait en poudre",
            base_uom=uom,
            requires_certificate_of_analysis=True,
        )
        regulated_variant = ProductVariant.objects.create(
            tenant=tenant, template=regulated_template
        )
        plain_template = ProductTemplate.objects.create(
            tenant=tenant,
            name="Carton d'emballage",
            base_uom=uom,
            requires_certificate_of_analysis=False,
        )
        plain_variant = ProductVariant.objects.create(tenant=tenant, template=plain_template)
    return tenant, regulated_variant, plain_variant


def test_requires_certificate_of_analysis(certificate_setup) -> None:
    tenant, regulated_variant, plain_variant = certificate_setup
    with use_tenant(tenant.id):
        assert requires_certificate_of_analysis(regulated_variant.id) is True
        assert requires_certificate_of_analysis(plain_variant.id) is False
        assert requires_certificate_of_analysis(uuid.uuid4()) is False
