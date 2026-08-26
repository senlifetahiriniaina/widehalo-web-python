"""Patrons et gradation (§5.4). Positionnement explicite du CDC : PAS un
logiciel de CAO (ne remplace ni Lectra, ni Optitex, ni Seamly2D) — aucun
ERP du marche, Odoo inclus, ne propose ce module nativement. Jamais de FK
Django vers `apps.catalog.models`/`apps.mrp.models` (regle de couplage
n°1) — references par UUID, resolues via `services.public`."""

from __future__ import annotations

from django.db import models

from apps.core.models.base import BaseModel


class PatSizeChart(BaseModel):
    GARMENT_SHIRT = "chemise"
    GARMENT_PANTS = "pantalon"
    GARMENT_DRESS = "robe"
    GARMENT_JACKET = "veste"
    GARMENT_SKIRT = "jupe"
    GARMENT_TSHIRT = "tshirt"
    GARMENT_JUMPSUIT = "combinaison"
    GARMENT_ACCESSORY = "accessoire"
    GARMENT_CHOICES = [
        (GARMENT_SHIRT, "Chemise"),
        (GARMENT_PANTS, "Pantalon"),
        (GARMENT_DRESS, "Robe"),
        (GARMENT_JACKET, "Veste"),
        (GARMENT_SKIRT, "Jupe"),
        (GARMENT_TSHIRT, "T-shirt"),
        (GARMENT_JUMPSUIT, "Combinaison"),
        (GARMENT_ACCESSORY, "Accessoire"),
    ]

    GENDER_MEN = "homme"
    GENDER_WOMEN = "femme"
    GENDER_UNISEX = "unisexe"
    GENDER_CHILD = "enfant"
    GENDER_CHOICES = [
        (GENDER_MEN, "Homme"),
        (GENDER_WOMEN, "Femme"),
        (GENDER_UNISEX, "Unisexe"),
        (GENDER_CHILD, "Enfant"),
    ]

    REGION_EU = "EU"
    REGION_US = "US"
    REGION_UK = "UK"
    REGION_FR = "FR"
    REGION_CUSTOM = "custom"
    REGION_CHOICES = [
        (REGION_EU, "EU"),
        (REGION_US, "US"),
        (REGION_UK, "UK"),
        (REGION_FR, "FR"),
        (REGION_CUSTOM, "Personnalise"),
    ]

    code = models.CharField(max_length=32)
    name = models.CharField(max_length=150)
    garment_type = models.CharField(max_length=16, choices=GARMENT_CHOICES)
    gender = models.CharField(max_length=16, choices=GENDER_CHOICES, default=GENDER_UNISEX)
    region_standard = models.CharField(max_length=16, choices=REGION_CHOICES, default=REGION_CUSTOM)
    # Ordonnee de la plus petite a la plus grande, ex. ["XS","S","M","L","XL"].
    sizes = models.JSONField(default=list)
    base_size = models.CharField(max_length=16)

    class Meta:
        db_table = "pat_size_chart"

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class PatMeasurementPoint(BaseModel):
    UNIT_CM = "cm"
    UNIT_MM = "mm"
    UNIT_INCH = "inch"
    UNIT_CHOICES = [(UNIT_CM, "cm"), (UNIT_MM, "mm"), (UNIT_INCH, "inch")]

    CATEGORY_WIDTH = "largeur"
    CATEGORY_LENGTH = "longueur"
    CATEGORY_CIRCUMFERENCE = "circonference"
    CATEGORY_ANGLE = "angle"
    CATEGORY_CHOICES = [
        (CATEGORY_WIDTH, "Largeur"),
        (CATEGORY_LENGTH, "Longueur"),
        (CATEGORY_CIRCUMFERENCE, "Circonference"),
        (CATEGORY_ANGLE, "Angle"),
    ]

    code = models.CharField(max_length=32)
    name = models.CharField(max_length=150)
    abbreviation = models.CharField(max_length=16, blank=True)
    unit = models.CharField(max_length=8, choices=UNIT_CHOICES, default=UNIT_CM)
    category = models.CharField(max_length=16, choices=CATEGORY_CHOICES, default=CATEGORY_LENGTH)
    description = models.TextField(blank=True)
    illustration = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "pat_measurement_point"

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class PatSizeChartValue(BaseModel):
    size_chart = models.ForeignKey(PatSizeChart, on_delete=models.CASCADE, related_name="values")
    measurement_point = models.ForeignKey(
        PatMeasurementPoint, on_delete=models.PROTECT, related_name="+"
    )
    size = models.CharField(max_length=16)
    value = models.DecimalField(max_digits=10, decimal_places=2)
    tolerance = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = "pat_size_chart_value"
        constraints = [
            models.UniqueConstraint(
                fields=["size_chart", "measurement_point", "size"], name="uniq_pat_size_chart_value"
            )
        ]

    def __str__(self) -> str:
        return f"{self.size_chart.code}:{self.measurement_point.code}:{self.size}"


class PatGradingRule(BaseModel):
    MODE_FIXED = "increment_fixe"
    MODE_PROGRESSIVE = "increment_progressif"
    MODE_PERCENTAGE = "pourcentage"
    MODE_FORMULA = "formule"
    MODE_CHOICES = [
        (MODE_FIXED, "Increment fixe"),
        (MODE_PROGRESSIVE, "Increment progressif"),
        (MODE_PERCENTAGE, "Pourcentage"),
        (MODE_FORMULA, "Formule"),
    ]

    size_chart = models.ForeignKey(
        PatSizeChart, on_delete=models.CASCADE, related_name="grading_rules"
    )
    measurement_point = models.ForeignKey(
        PatMeasurementPoint, on_delete=models.PROTECT, related_name="+"
    )
    mode = models.CharField(max_length=24, choices=MODE_CHOICES)
    value = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    formula = models.CharField(max_length=255, blank=True)
    from_size = models.CharField(max_length=16)
    to_size = models.CharField(max_length=16)

    class Meta:
        db_table = "pat_grading_rule"

    def __str__(self) -> str:
        return (
            f"{self.size_chart.code}:{self.measurement_point.code} "
            f"[{self.from_size}-{self.to_size}]"
        )
