"""Patrons et gradation (§5.4). Positionnement explicite du CDC : PAS un
logiciel de CAO (ne remplace ni Lectra, ni Optitex, ni Seamly2D) — aucun
ERP du marche, Odoo inclus, ne propose ce module nativement. Jamais de FK
Django vers `apps.catalog.models`/`apps.mrp.models` (regle de couplage
n°1) — references par UUID, resolues via `services.public`."""

from __future__ import annotations

from django.db import models

from apps.core.models.base import BaseModel, ReferenceMixin


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


class PatPattern(BaseModel, ReferenceMixin):
    """§5.4.2 : PAS un logiciel de CAO. RG-PAT-6 : un patron valide se fige,
    toute modification cree une nouvelle version."""

    STATE_DRAFT = "draft"
    STATE_VALIDATED = "validated"
    STATE_IN_PRODUCTION = "in_production"
    STATE_OBSOLETE = "obsolete"
    STATE_CHOICES = [
        (STATE_DRAFT, "Brouillon"),
        (STATE_VALIDATED, "Valide"),
        (STATE_IN_PRODUCTION, "En production"),
        (STATE_OBSOLETE, "Obsolete"),
    ]

    code = models.CharField(max_length=32)
    name = models.CharField(max_length=150)
    # Reference vers `catalog.ProductTemplate` — UUID simple.
    product_template_id = models.UUIDField(null=True, blank=True)
    size_chart = models.ForeignKey(PatSizeChart, on_delete=models.PROTECT, related_name="patterns")
    version = models.PositiveIntegerField(default=1)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_DRAFT)
    designer = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    season = models.CharField(max_length=64, blank=True)
    collection = models.CharField(max_length=64, blank=True)
    date_created = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    parent_pattern = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="versions"
    )

    class Meta:
        db_table = "pat_pattern"

    def __str__(self) -> str:
        return f"{self.code} v{self.version}"


class PatPatternPiece(BaseModel):
    pattern = models.ForeignKey(PatPattern, on_delete=models.CASCADE, related_name="pieces")
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=150)
    qty_per_garment = models.PositiveSmallIntegerField(default=1)
    # Reference vers `catalog.ProductVariant` (matiere) — UUID simple.
    material_variant_id = models.UUIDField(null=True, blank=True)
    grain_direction = models.CharField(max_length=32, blank=True)
    seam_allowance_mm = models.DecimalField(max_digits=6, decimal_places=2, default=10)
    is_lining = models.BooleanField(default=False)
    is_interfacing = models.BooleanField(default=False)
    symmetry = models.CharField(max_length=16, blank=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "pat_pattern_piece"

    def __str__(self) -> str:
        return f"{self.pattern.code}:{self.code}"


class PatPieceGeometry(BaseModel):
    """RG-PAT-3 : geometrie SVG par taille. Peut etre dessinee (import),
    importee, ou generee depuis un gabarit parametrique simple (cf.
    `services/patterns.py::generate_piece_geometry`) — explicitement pas un
    rendu de patronage professionnel."""

    piece = models.ForeignKey(PatPatternPiece, on_delete=models.CASCADE, related_name="geometries")
    size = models.CharField(max_length=16)
    svg_path = models.TextField(blank=True)
    points = models.JSONField(default=list, blank=True)
    area_cm2 = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    perimeter_cm = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    bounding_box = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "pat_piece_geometry"
        constraints = [
            models.UniqueConstraint(fields=["piece", "size"], name="uniq_pat_piece_geometry")
        ]

    def __str__(self) -> str:
        return f"{self.piece} — {self.size}"


class PatPieceMeasure(BaseModel):
    piece = models.ForeignKey(PatPatternPiece, on_delete=models.CASCADE, related_name="measures")
    measurement_point = models.ForeignKey(
        PatMeasurementPoint, on_delete=models.PROTECT, related_name="+"
    )
    size = models.CharField(max_length=16)
    value = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = "pat_piece_measure"
        constraints = [
            models.UniqueConstraint(
                fields=["piece", "measurement_point", "size"], name="uniq_pat_piece_measure"
            )
        ]

    def __str__(self) -> str:
        return f"{self.piece} — {self.measurement_point.code}:{self.size}"
