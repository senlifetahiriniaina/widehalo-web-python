from __future__ import annotations

from decimal import Decimal

import pytest

from apps.catalog.models import ProductTemplate, ProductVariant, TextileSpec, UnitOfMeasure
from apps.catalog.services.textile import length_from_weight_kg, weight_kg_from_length
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def textile_spec():
    tenant = Tenant.objects.create(code="CAT-TEX", name="Catalog Textile Tenant")
    with use_tenant(tenant.id):
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="M", name="Metre", category=UnitOfMeasure.CATEGORY_LENGTH
        )
        template = ProductTemplate.objects.create(
            tenant=tenant, name="Coton", base_uom=uom, reference="TPL-TEX-0001"
        )
        variant = ProductVariant.objects.create(
            tenant=tenant, template=template, reference="VAR-TEX-0001"
        )
        spec = TextileSpec.objects.create(
            tenant=tenant,
            variant=variant,
            material="Coton",
            weight_gsm=Decimal("200"),
            width_cm=Decimal("150"),
        )
        return tenant, spec


def test_weight_to_length_and_back_round_trips(textile_spec) -> None:
    _tenant, spec = textile_spec

    length_m = length_from_weight_kg(spec, Decimal("30"))
    # 30 kg = 30000 g ; laize 1.5 m ; grammage 200 g/m2 -> 30000/(1.5*200) = 100 m
    assert length_m == Decimal("100")

    weight_kg = weight_kg_from_length(spec, length_m)
    assert weight_kg == Decimal("30")
