"""Le catalogue est organise en parent (`ProductTemplate`, porteur du
champ `is_sellable`) / fils (`ProductVariant`) — tests du gap public
`is_variant_sellable`/`list_sellable_variants` consomme par `sales` pour
restreindre les lignes de devis/commande aux seuls produits vendables."""

from __future__ import annotations

import uuid

import pytest

from apps.catalog.models import ProductTemplate, ProductVariant, UnitOfMeasure
from apps.catalog.services.public import is_variant_sellable, list_sellable_variants
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def sellable_setup():
    tenant = Tenant.objects.create(code="CAT-SELL", name="Sellable Tenant")
    with use_tenant(tenant.id):
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="U", name="Unite", category=UnitOfMeasure.CATEGORY_COUNT
        )
        sellable_template = ProductTemplate.objects.create(
            tenant=tenant, name="Veste hi-vis", base_uom=uom, is_sellable=True
        )
        sellable_variant = ProductVariant.objects.create(tenant=tenant, template=sellable_template)
        internal_template = ProductTemplate.objects.create(
            tenant=tenant, name="Fermeture eclair", base_uom=uom, is_sellable=False
        )
        internal_variant = ProductVariant.objects.create(tenant=tenant, template=internal_template)
    return tenant, sellable_variant, internal_variant


def test_is_variant_sellable(sellable_setup) -> None:
    tenant, sellable_variant, internal_variant = sellable_setup
    with use_tenant(tenant.id):
        assert is_variant_sellable(sellable_variant.id) is True
        assert is_variant_sellable(internal_variant.id) is False
        assert is_variant_sellable(uuid.uuid4()) is False


def test_list_sellable_variants_excludes_non_sellable(sellable_setup) -> None:
    tenant, sellable_variant, internal_variant = sellable_setup
    with use_tenant(tenant.id):
        results = list_sellable_variants()
    ids = {row["id"] for row in results}
    assert str(sellable_variant.id) in ids
    assert str(internal_variant.id) not in ids
