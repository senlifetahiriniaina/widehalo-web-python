"""Référentiel catalogue : unités de mesure et conversions, catégories,
attributs/valeurs generateurs de variantes, gammes de produits (template ->
variantes), specs textiles, information fournisseur (couplage generique
vers `partners` par UUID uniquement, jamais de FK Django), listes de prix en
cascade, conditionnement."""

from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.core.models.base import BaseModel, ReferenceMixin


class UnitOfMeasure(BaseModel):
    CATEGORY_WEIGHT = "weight"
    CATEGORY_LENGTH = "length"
    CATEGORY_COUNT = "count"
    CATEGORY_VOLUME = "volume"
    CATEGORY_CHOICES = [
        (CATEGORY_WEIGHT, "Poids"),
        (CATEGORY_LENGTH, "Longueur"),
        (CATEGORY_COUNT, "Comptage"),
        (CATEGORY_VOLUME, "Volume"),
    ]

    code = models.CharField(max_length=16)
    name = models.CharField(max_length=64)
    category = models.CharField(max_length=16, choices=CATEGORY_CHOICES)
    is_base = models.BooleanField(default=False)

    class Meta:
        db_table = "catalog_unit_of_measure"

    def __str__(self) -> str:
        return self.code


class UnitConversion(BaseModel):
    """Facteur multiplicatif : `1 <from_unit> == factor <to_unit>`, dans la
    meme categorie (pas de conversion poids<->longueur ici — cf.
    `services/textile.py` pour la conversion tissu specifique qui a besoin
    du grammage et de la laize)."""

    from_unit = models.ForeignKey(UnitOfMeasure, on_delete=models.CASCADE, related_name="+")
    to_unit = models.ForeignKey(UnitOfMeasure, on_delete=models.CASCADE, related_name="+")
    factor = models.DecimalField(max_digits=18, decimal_places=8)

    class Meta:
        db_table = "catalog_unit_conversion"


class Category(BaseModel):
    name = models.CharField(max_length=120)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children"
    )

    class Meta:
        db_table = "catalog_category"
        verbose_name_plural = "categories"

    def __str__(self) -> str:
        return self.name


class Attribute(BaseModel):
    name = models.CharField(max_length=80)

    class Meta:
        db_table = "catalog_attribute"

    def __str__(self) -> str:
        return self.name


class AttributeValue(BaseModel):
    attribute = models.ForeignKey(Attribute, on_delete=models.CASCADE, related_name="values")
    value = models.CharField(max_length=80)

    class Meta:
        db_table = "catalog_attribute_value"

    def __str__(self) -> str:
        return f"{self.attribute.name}: {self.value}"


MAX_VARIANT_GENERATING_ATTRIBUTES = 2
MAX_VARIANTS_PER_TEMPLATE = 50


class ProductTemplate(BaseModel, ReferenceMixin):
    name = models.CharField(max_length=200)
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="templates"
    )
    base_uom = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name="+")
    variant_attributes = models.ManyToManyField(Attribute, blank=True, related_name="templates")
    base_price_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)

    class Meta:
        db_table = "catalog_product_template"

    def __str__(self) -> str:
        return f"{self.reference} — {self.name}"


class ProductVariant(BaseModel, ReferenceMixin):
    template = models.ForeignKey(ProductTemplate, on_delete=models.CASCADE, related_name="variants")
    attribute_values = models.ManyToManyField(AttributeValue, related_name="variants")

    class Meta:
        db_table = "catalog_product_variant"

    def __str__(self) -> str:
        return self.reference


class TextileSpec(BaseModel):
    variant = models.OneToOneField(
        ProductVariant, on_delete=models.CASCADE, related_name="textile_spec"
    )
    material = models.CharField(max_length=120, blank=True)
    composition = models.JSONField(default=dict, blank=True)
    weight_gsm = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Grammage, g/m²"
    )
    width_cm = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Laize, cm"
    )
    certifications = ArrayField(models.CharField(max_length=64), default=list, blank=True)

    class Meta:
        db_table = "catalog_textile_spec"


class ProductSupplierInfo(BaseModel):
    """Information fournisseur d'une variante. `partner_id` reste un UUID
    simple, JAMAIS une FK Django vers `apps.partners.models.Partner` — le
    couplage entre `catalog` et `partners` ne doit transiter que par
    `partners.services.public` (cf. regle de couplage n°1)."""

    variant = models.ForeignKey(
        ProductVariant, on_delete=models.CASCADE, related_name="supplier_infos"
    )
    partner_id = models.UUIDField()
    supplier_reference = models.CharField(max_length=100, blank=True)
    price_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    lead_time_days = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "catalog_product_supplier_info"


class PriceList(BaseModel):
    KIND_DEFAULT = "default"
    KIND_CLIENT = "client"
    KIND_CONTRACT = "contract"
    KIND_CHOICES = [
        (KIND_DEFAULT, "Liste par defaut"),
        (KIND_CLIENT, "Liste client"),
        (KIND_CONTRACT, "Contrat"),
    ]

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    # Meme convention que ProductSupplierInfo : UUID simple, jamais de FK vers `partners`.
    partner_id = models.UUIDField(null=True, blank=True)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "catalog_price_list"


class PriceListItem(BaseModel):
    price_list = models.ForeignKey(PriceList, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey(
        ProductVariant, on_delete=models.CASCADE, related_name="price_items"
    )
    price_mga = models.DecimalField(max_digits=18, decimal_places=4)

    class Meta:
        db_table = "catalog_price_list_item"
        constraints = [
            models.UniqueConstraint(fields=["price_list", "variant"], name="uniq_price_list_item")
        ]


class Packaging(BaseModel):
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name="packagings")
    unit_count = models.PositiveIntegerField(default=1)
    uom = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name="+")
    barcode = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "catalog_packaging"
