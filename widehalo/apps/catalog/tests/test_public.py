"""Tests du contrat public de `catalog` (`apps/catalog/services/public.py`)
— seule surface que les autres apps metier ont le droit d'importer. Couvre
ici le gap ajoute pour RG-SAL-3 (S3 du sous-sequencement `sales`, cf.
plan) : `get_variant_template_id`."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.catalog.models import (
    ProductSupplierInfo,
    ProductTemplate,
    ProductVariant,
    TextileSpec,
    UnitOfMeasure,
)
from apps.catalog.services.public import (
    convert_textile_measurement,
    get_supplier_lead_time_days,
    get_variant_template_id,
    search_sellable_variants,
    select_preferred_supplier,
)
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def variant_setup():
    tenant = Tenant.objects.create(code="CAT-PUB", name="Catalog Public Tenant")
    with use_tenant(tenant.id):
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="U", name="Unite", category=UnitOfMeasure.CATEGORY_COUNT
        )
        template = ProductTemplate.objects.create(
            tenant=tenant, name="Polo", base_uom=uom, reference="TPL-PUB-0001"
        )
        variant = ProductVariant.objects.create(
            tenant=tenant, template=template, reference="VAR-PUB-0001"
        )
        return tenant, template, variant


def test_get_variant_template_id_resolves_existing_variant(variant_setup) -> None:
    tenant, template, variant = variant_setup
    with use_tenant(tenant.id):
        assert get_variant_template_id(variant.id) == template.id


def test_get_variant_template_id_returns_none_for_unknown_variant(variant_setup) -> None:
    tenant, _template, _variant = variant_setup
    with use_tenant(tenant.id):
        assert get_variant_template_id(uuid.uuid4()) is None


def test_search_sellable_variants_filters_by_reference_or_name(variant_setup) -> None:
    """Gap ajoute pour le module `pos` (§13.5, POS-1/POS-2 — recherche
    article a la frappe/au scan)."""
    tenant, template, variant = variant_setup
    with use_tenant(tenant.id):
        other_template = ProductTemplate.objects.create(
            tenant=tenant, name="Chemise", base_uom=template.base_uom, reference="TPL-PUB-0002"
        )
        ProductVariant.objects.create(tenant=tenant, template=other_template, reference="VAR-PUB-0002")

        by_reference = search_sellable_variants("VAR-PUB-0001")
        by_name = search_sellable_variants("chemise")
        empty_query = search_sellable_variants("")

        assert [row["id"] for row in by_reference] == [str(variant.id)]
        assert len(by_name) == 1
        assert by_name[0]["label"].endswith("Chemise")
        assert len(empty_query) == 2
        assert all("unit_price_mga" in row for row in empty_query)


def test_search_sellable_variants_excludes_non_sellable_templates(variant_setup) -> None:
    tenant, template, _variant = variant_setup
    with use_tenant(tenant.id):
        hidden_template = ProductTemplate.objects.create(
            tenant=tenant,
            name="Matière première",
            base_uom=template.base_uom,
            reference="TPL-PUB-0003",
            is_sellable=False,
        )
        ProductVariant.objects.create(tenant=tenant, template=hidden_template, reference="VAR-PUB-0003")

        results = search_sellable_variants("Matière")

        assert results == []


def test_get_supplier_lead_time_days_returns_minimum_across_suppliers(variant_setup) -> None:
    """RG-SAL-7 (S6 du sous-sequencement `sales`) : le minimum, l'hypothese
    la plus optimiste, sert de delai fournisseur par defaut."""
    tenant, _template, variant = variant_setup
    with use_tenant(tenant.id):
        partner_fast = uuid.uuid4()
        partner_slow = uuid.uuid4()
        ProductSupplierInfo.objects.create(
            tenant=tenant, variant=variant, partner_id=partner_fast, lead_time_days=5
        )
        ProductSupplierInfo.objects.create(
            tenant=tenant, variant=variant, partner_id=partner_slow, lead_time_days=20
        )

        assert get_supplier_lead_time_days(variant.id) == 5
        assert get_supplier_lead_time_days(variant.id, partner_id=partner_slow) == 20


def test_get_supplier_lead_time_days_returns_none_without_supplier_info(variant_setup) -> None:
    tenant, _template, variant = variant_setup
    with use_tenant(tenant.id):
        assert get_supplier_lead_time_days(variant.id) is None


def test_get_supplier_lead_time_days_returns_none_for_unknown_variant(variant_setup) -> None:
    tenant, _template, _variant = variant_setup
    with use_tenant(tenant.id):
        assert get_supplier_lead_time_days(uuid.uuid4()) is None


# RG-PUR-1 (gap PU2 du sous-sequencement `purchase`) : priority > prix > delai.
def test_select_preferred_supplier_orders_by_priority_then_price_then_lead_time(
    variant_setup,
) -> None:
    tenant, _template, variant = variant_setup
    with use_tenant(tenant.id):
        # Priorite haute (valeur basse) gagne malgre un prix/delai moins bons.
        best = ProductSupplierInfo.objects.create(
            tenant=tenant,
            variant=variant,
            partner_id=uuid.uuid4(),
            price_mga=Decimal("900"),
            lead_time_days=10,
            priority=1,
            origin=ProductSupplierInfo.ORIGIN_IMPORT_CHINE,
            min_qty=Decimal("5"),
        )
        ProductSupplierInfo.objects.create(
            tenant=tenant,
            variant=variant,
            partner_id=uuid.uuid4(),
            price_mga=Decimal("100"),
            lead_time_days=1,
            priority=5,
        )

        result = select_preferred_supplier(variant.id)
        assert result == {
            "partner_id": best.partner_id,
            "price_mga": Decimal("900.0000"),
            "lead_time_days": 10,
            "origin": ProductSupplierInfo.ORIGIN_IMPORT_CHINE,
            "min_qty": Decimal("5.0000"),
        }


def test_select_preferred_supplier_breaks_priority_tie_by_price_then_lead_time(
    variant_setup,
) -> None:
    tenant, _template, variant = variant_setup
    with use_tenant(tenant.id):
        ProductSupplierInfo.objects.create(
            tenant=tenant,
            variant=variant,
            partner_id=uuid.uuid4(),
            price_mga=Decimal("300"),
            lead_time_days=1,
            priority=5,
        )
        cheapest = ProductSupplierInfo.objects.create(
            tenant=tenant,
            variant=variant,
            partner_id=uuid.uuid4(),
            price_mga=Decimal("100"),
            lead_time_days=9,
            priority=5,
        )

        result = select_preferred_supplier(variant.id)
        assert result is not None
        assert result["partner_id"] == cheapest.partner_id


def test_select_preferred_supplier_returns_none_without_supplier_info(variant_setup) -> None:
    tenant, _template, variant = variant_setup
    with use_tenant(tenant.id):
        assert select_preferred_supplier(variant.id) is None


def test_select_preferred_supplier_returns_none_for_unknown_variant(variant_setup) -> None:
    tenant, _template, _variant = variant_setup
    with use_tenant(tenant.id):
        assert select_preferred_supplier(uuid.uuid4()) is None


# RG-STK-5 (gap ST3 du sous-sequencement `stocks`) : conversion m/kg textile.
def test_convert_textile_measurement_round_trips_length_to_weight_and_back(variant_setup) -> None:
    tenant, _template, variant = variant_setup
    with use_tenant(tenant.id):
        TextileSpec.objects.create(
            tenant=tenant, variant=variant, weight_gsm=Decimal("200"), width_cm=Decimal("150")
        )

        result = convert_textile_measurement(variant.id, length_m=Decimal("100"))
        assert result is not None
        # 100 m * 1.5 m * 200 g/m2 = 30000 g = 30 kg.
        assert result["weight_kg"] == Decimal("30")
        assert result["length_m"] == Decimal("100")

        back = convert_textile_measurement(variant.id, weight_kg=result["weight_kg"])
        assert back is not None
        assert back["length_m"] == Decimal("100")
        assert back["weight_kg"] == Decimal("30")


def test_convert_textile_measurement_returns_none_without_textile_spec(variant_setup) -> None:
    tenant, _template, variant = variant_setup
    with use_tenant(tenant.id):
        assert convert_textile_measurement(variant.id, length_m=Decimal("10")) is None


def test_convert_textile_measurement_returns_none_when_dimensions_missing(variant_setup) -> None:
    tenant, _template, variant = variant_setup
    with use_tenant(tenant.id):
        TextileSpec.objects.create(tenant=tenant, variant=variant)
        assert convert_textile_measurement(variant.id, length_m=Decimal("10")) is None


def test_convert_textile_measurement_returns_none_for_unknown_variant(variant_setup) -> None:
    tenant, _template, _variant = variant_setup
    with use_tenant(tenant.id):
        assert convert_textile_measurement(uuid.uuid4(), length_m=Decimal("10")) is None


def test_convert_textile_measurement_refuses_both_or_neither(variant_setup) -> None:
    tenant, _template, variant = variant_setup
    with use_tenant(tenant.id):
        with pytest.raises(ValidationError):
            convert_textile_measurement(variant.id)
        with pytest.raises(ValidationError):
            convert_textile_measurement(variant.id, length_m=Decimal("1"), weight_kg=Decimal("1"))
