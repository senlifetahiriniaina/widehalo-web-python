"""Production (§5.3) : ateliers/postes de charge/operations/gammes, puis
nomenclatures/ordres de fabrication/CRA-CRI (etapes suivantes). Jamais de
FK Django vers `apps.catalog.models`/`apps.partners.models` (regle de
couplage n°1) — un produit/tiers est reference par son UUID, resolu via
`services.public`."""

from __future__ import annotations

from django.db import models

from apps.core.models.base import BaseModel


class MrpWorkshop(BaseModel):
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=150)
    address = models.CharField(max_length=255, blank=True)
    manager = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    capacity_hours_day = models.DecimalField(max_digits=6, decimal_places=2, default=8)
    # `warehouse_id`/`partner_id` : reference future vers `stocks`/`partners`
    # (modules pas encore construits) — UUID simple, jamais de FK.
    warehouse_id = models.UUIDField(null=True, blank=True)
    is_subcontractor = models.BooleanField(default=False)
    partner_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "mrp_workshop"

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class MrpWorkcenter(BaseModel):
    TYPE_CUTTING = "coupe"
    TYPE_SEWING = "couture"
    TYPE_EMBROIDERY = "broderie"
    TYPE_PRINTING = "impression"
    TYPE_FINISHING = "finition"
    TYPE_CONTROL = "controle"
    TYPE_PACKAGING = "emballage"
    TYPE_CHOICES = [
        (TYPE_CUTTING, "Coupe"),
        (TYPE_SEWING, "Couture"),
        (TYPE_EMBROIDERY, "Broderie"),
        (TYPE_PRINTING, "Impression"),
        (TYPE_FINISHING, "Finition"),
        (TYPE_CONTROL, "Controle"),
        (TYPE_PACKAGING, "Emballage"),
    ]

    workshop = models.ForeignKey(MrpWorkshop, on_delete=models.CASCADE, related_name="workcenters")
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=150)
    type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    capacity_units_hour = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cost_per_hour_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    setup_time_min = models.PositiveIntegerField(default=0)
    cleanup_time_min = models.PositiveIntegerField(default=0)
    efficiency_pct = models.DecimalField(max_digits=5, decimal_places=2, default=100)

    class Meta:
        db_table = "mrp_workcenter"

    def __str__(self) -> str:
        return f"{self.workshop.code}:{self.code}"


class MrpOperation(BaseModel):
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=150)
    workcenter_type = models.CharField(max_length=16, choices=MrpWorkcenter.TYPE_CHOICES)
    default_duration_min = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True)

    class Meta:
        db_table = "mrp_operation"

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class MrpRouting(BaseModel):
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=150)
    # Reference vers `catalog.ProductTemplate` — UUID simple, resolu via
    # `catalog.services.public`.
    product_template_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "mrp_routing"

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class MrpRoutingStep(BaseModel):
    routing = models.ForeignKey(MrpRouting, on_delete=models.CASCADE, related_name="steps")
    sequence = models.PositiveSmallIntegerField(default=0)
    operation = models.ForeignKey(MrpOperation, on_delete=models.PROTECT, related_name="+")
    workcenter = models.ForeignKey(MrpWorkcenter, on_delete=models.PROTECT, related_name="+")
    duration_min = models.PositiveIntegerField(default=0)
    # Liste de sequences d'etapes prealables (dependances), pas de FK M2M
    # pour rester simple — coherent avec un DAG petit (une gamme n'a pas des
    # centaines d'etapes).
    depends_on = models.JSONField(default=list, blank=True)
    quality_check = models.BooleanField(default=False)
    instructions = models.TextField(blank=True)

    class Meta:
        db_table = "mrp_routing_step"
        ordering = ["sequence"]

    def __str__(self) -> str:
        return f"{self.routing.code}#{self.sequence}"


class MrpBom(BaseModel):
    TYPE_MANUFACTURE = "manufacture"
    TYPE_KIT = "kit"
    TYPE_SUBCONTRACT = "subcontract"
    TYPE_CHOICES = [
        (TYPE_MANUFACTURE, "Fabrication"),
        (TYPE_KIT, "Kit"),
        (TYPE_SUBCONTRACT, "Sous-traitance"),
    ]

    STATE_DRAFT = "draft"
    STATE_ACTIVE = "active"
    STATE_OBSOLETE = "obsolete"
    STATE_CHOICES = [
        (STATE_DRAFT, "Brouillon"),
        (STATE_ACTIVE, "Active"),
        (STATE_OBSOLETE, "Obsolete"),
    ]

    code = models.CharField(max_length=32)
    # Jamais de FK Django vers `catalog` (regle de couplage n°1) — resolu
    # via `catalog.services.public`.
    product_template_id = models.UUIDField()
    variant_id = models.UUIDField(null=True, blank=True)
    type = models.CharField(max_length=16, choices=TYPE_CHOICES, default=TYPE_MANUFACTURE)
    qty = models.DecimalField(max_digits=18, decimal_places=4, default=1)
    uom_code = models.CharField(max_length=16, blank=True)
    routing = models.ForeignKey(
        MrpRouting, null=True, blank=True, on_delete=models.SET_NULL, related_name="boms"
    )
    version = models.PositiveIntegerField(default=1)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_DRAFT)
    parent_bom = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="versions"
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "mrp_bom"

    def __str__(self) -> str:
        return f"{self.code} v{self.version}"


class MrpBomLine(BaseModel):
    bom = models.ForeignKey(MrpBom, on_delete=models.CASCADE, related_name="lines")
    sequence = models.PositiveSmallIntegerField(default=0)
    component_template_id = models.UUIDField()
    component_variant_id = models.UUIDField(null=True, blank=True)
    qty = models.DecimalField(max_digits=18, decimal_places=4, default=1)
    uom_code = models.CharField(max_length=16, blank=True)
    # RG-MRP-4 : consommation planifiee = qty * (1 + waste_pct/100).
    waste_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    # RG-MRP-3 : ligne conditionnelle a certaines valeurs d'attribut (ex.
    # doublure uniquement sur la couleur noire) — codes d'attribut-valeur en
    # texte libre, jamais de FK vers `catalog`.
    apply_on_attribute_values = models.JSONField(default=list, blank=True)
    # RG-MRP-2 : {"XS": 1.15, "S": 1.20, ...} — consommation differente par
    # taille sans dupliquer la nomenclature. Vide => `qty` s'applique
    # uniformement.
    qty_by_size = models.JSONField(default=dict, blank=True)
    is_optional = models.BooleanField(default=False)
    operation = models.ForeignKey(
        MrpOperation, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "mrp_bom_line"
        ordering = ["sequence"]

    def __str__(self) -> str:
        return f"{self.bom.code}#{self.sequence}"
