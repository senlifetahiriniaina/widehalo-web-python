from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from apps.catalog.models import (
    PriceList,
    PriceListItem,
    ProductTemplate,
    ProductVariant,
    UnitOfMeasure,
)
from apps.catalog.services.pricing import get_price
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def variant():
    tenant = Tenant.objects.create(code="CAT-PRICE", name="Catalog Pricing Tenant")
    with use_tenant(tenant.id):
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PC", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )
        template = ProductTemplate.objects.create(
            tenant=tenant,
            name="Chemise",
            base_uom=uom,
            reference="TPL-PRICE-0001",
            base_price_mga=Decimal("10000"),
        )
        variant = ProductVariant.objects.create(
            tenant=tenant, template=template, reference="VAR-PRICE-0001"
        )
        return tenant, variant


def _add_price(tenant, variant, kind, price, partner_id=None):
    price_list = PriceList.objects.create(
        tenant=tenant, name=kind, kind=kind, partner_id=partner_id
    )
    PriceListItem.objects.create(
        tenant=tenant, price_list=price_list, variant=variant, price_mga=price
    )


def test_falls_back_to_catalogue_price_when_nothing_else_defined(variant) -> None:
    tenant, v = variant
    with use_tenant(tenant.id):
        assert get_price(v) == Decimal("10000")


def test_default_price_list_overrides_catalogue_price(variant) -> None:
    tenant, v = variant
    with use_tenant(tenant.id):
        _add_price(tenant, v, PriceList.KIND_DEFAULT, Decimal("9000"))
        assert get_price(v) == Decimal("9000")


def test_client_price_list_overrides_default(variant) -> None:
    tenant, v = variant
    partner_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _add_price(tenant, v, PriceList.KIND_DEFAULT, Decimal("9000"))
        _add_price(tenant, v, PriceList.KIND_CLIENT, Decimal("8000"), partner_id=partner_id)
        assert get_price(v, partner_id=partner_id) == Decimal("8000")
        # Un autre partenaire ne voit pas cette liste client.
        assert get_price(v, partner_id=uuid.uuid4()) == Decimal("9000")


def test_contract_price_overrides_client_and_default(variant) -> None:
    tenant, v = variant
    partner_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _add_price(tenant, v, PriceList.KIND_DEFAULT, Decimal("9000"))
        _add_price(tenant, v, PriceList.KIND_CLIENT, Decimal("8000"), partner_id=partner_id)
        _add_price(tenant, v, PriceList.KIND_CONTRACT, Decimal("7000"), partner_id=partner_id)
        assert get_price(v, partner_id=partner_id) == Decimal("7000")
