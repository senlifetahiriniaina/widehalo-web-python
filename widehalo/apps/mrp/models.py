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
