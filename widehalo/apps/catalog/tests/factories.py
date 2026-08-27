"""Factories factory_boy pour les modeles du module `catalog` — une par
modele concret (couche T1 du plan de durcissement, CDC §14 couches).

`tenant` est resolu via un `SubFactory` a chemin pointe vers
`apps.core.tests.factories.TenantFactory` (resolution paresseuse). Les
sous-objets d'un meme graphe partagent le tenant du parent via
`factory.SelfAttribute("..tenant")`. `partner_id` reste toujours un simple
UUID (jamais une FK Django vers `apps.partners` — regle de couplage n°1)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import factory

from apps.catalog.models import (
    Attribute,
    AttributeValue,
    CatalogCertification,
    CatalogStandard,
    Category,
    Packaging,
    PriceList,
    PriceListItem,
    ProductSupplierInfo,
    ProductTemplate,
    ProductVariant,
    TextileSpec,
    UnitConversion,
    UnitOfMeasure,
)


class UnitOfMeasureFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = UnitOfMeasure

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"UOM{n}")
    name = factory.Sequence(lambda n: f"Unite {n}")
    category = UnitOfMeasure.CATEGORY_COUNT


class UnitConversionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = UnitConversion

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    from_unit = factory.SubFactory(UnitOfMeasureFactory, tenant=factory.SelfAttribute("..tenant"))
    to_unit = factory.SubFactory(UnitOfMeasureFactory, tenant=factory.SelfAttribute("..tenant"))
    factor = Decimal("1.00000000")


class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Category

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Categorie {n}")


class AttributeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Attribute

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Attribut {n}")


class AttributeValueFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AttributeValue

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    attribute = factory.SubFactory(AttributeFactory, tenant=factory.SelfAttribute("..tenant"))
    value = factory.Sequence(lambda n: f"Valeur {n}")


class ProductTemplateFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProductTemplate

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Gamme {n}")
    base_uom = factory.SubFactory(UnitOfMeasureFactory, tenant=factory.SelfAttribute("..tenant"))
    base_price_mga = Decimal("1000.0000")


class ProductVariantFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProductVariant

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    template = factory.SubFactory(ProductTemplateFactory, tenant=factory.SelfAttribute("..tenant"))


class TextileSpecFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TextileSpec

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    variant = factory.SubFactory(ProductVariantFactory, tenant=factory.SelfAttribute("..tenant"))
    material = "Coton"
    composition = factory.LazyFunction(lambda: {"coton": 100})
    weight_gsm = Decimal("180.00")
    width_cm = Decimal("150.00")


class ProductSupplierInfoFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProductSupplierInfo

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    variant = factory.SubFactory(ProductVariantFactory, tenant=factory.SelfAttribute("..tenant"))
    partner_id = factory.LazyFunction(uuid.uuid4)
    supplier_reference = factory.Sequence(lambda n: f"SUPREF{n}")
    price_mga = Decimal("500.0000")


class PriceListFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PriceList

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Liste de prix {n}")
    kind = PriceList.KIND_DEFAULT


class PriceListItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PriceListItem

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    price_list = factory.SubFactory(PriceListFactory, tenant=factory.SelfAttribute("..tenant"))
    variant = factory.SubFactory(ProductVariantFactory, tenant=factory.SelfAttribute("..tenant"))
    price_mga = Decimal("1200.0000")


class PackagingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Packaging

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    variant = factory.SubFactory(ProductVariantFactory, tenant=factory.SelfAttribute("..tenant"))
    unit_count = 12
    uom = factory.SubFactory(UnitOfMeasureFactory, tenant=factory.SelfAttribute("..tenant"))
    barcode = factory.Sequence(lambda n: f"{1000000000000 + n}")


class CatalogStandardFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CatalogStandard

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"STD{n}")
    name = factory.Sequence(lambda n: f"Norme {n}")


class CatalogCertificationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CatalogCertification

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    variant = factory.SubFactory(ProductVariantFactory, tenant=factory.SelfAttribute("..tenant"))
    standard = factory.SubFactory(CatalogStandardFactory, tenant=factory.SelfAttribute("..tenant"))
    partner_id = factory.LazyFunction(uuid.uuid4)
