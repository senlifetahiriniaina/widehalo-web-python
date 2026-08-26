"""Production (§5.3) : ateliers/postes de charge/operations/gammes, puis
nomenclatures/ordres de fabrication/CRA-CRI (etapes suivantes). Jamais de
FK Django vers `apps.catalog.models`/`apps.partners.models` (regle de
couplage n°1) — un produit/tiers est reference par son UUID, resolu via
`services.public`."""

from __future__ import annotations

from django.db import models
from django_fsm import FSMField, transition

from apps.core.models.base import BaseModel, ReferenceMixin


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


class MrpOrder(BaseModel, ReferenceMixin):
    """Ordre de fabrication (§5.3.4). `state` porte le workflow normatif
    du CDC (brouillon -> confirme -> matieres reservees -> en production ->
    controle qualite -> termine -> cloture, embranchements annule et
    suspendu). Le detail des composants a consommer (RG-MRP-2/3/4) est
    materialise a la confirmation via `mrp.services.bom.explode()`."""

    STATE_DRAFT = "draft"
    STATE_CONFIRMED = "confirmed"
    STATE_RESERVED = "reserved"
    STATE_IN_PRODUCTION = "in_production"
    STATE_QUALITY_CONTROL = "quality_control"
    STATE_DONE = "done"
    STATE_CLOSED = "closed"
    STATE_CANCELLED = "cancelled"
    STATE_SUSPENDED = "suspended"
    STATE_CHOICES = [
        (STATE_DRAFT, "Brouillon"),
        (STATE_CONFIRMED, "Confirme"),
        (STATE_RESERVED, "Matieres reservees"),
        (STATE_IN_PRODUCTION, "En production"),
        (STATE_QUALITY_CONTROL, "Controle qualite"),
        (STATE_DONE, "Termine"),
        (STATE_CLOSED, "Cloture"),
        (STATE_CANCELLED, "Annule"),
        (STATE_SUSPENDED, "Suspendu"),
    ]

    PRIORITY_LOW = "low"
    PRIORITY_NORMAL = "normal"
    PRIORITY_HIGH = "high"
    PRIORITY_CHOICES = [
        (PRIORITY_LOW, "Basse"),
        (PRIORITY_NORMAL, "Normale"),
        (PRIORITY_HIGH, "Haute"),
    ]

    variant_id = models.UUIDField(null=True, blank=True)
    qty = models.DecimalField(max_digits=18, decimal_places=4, default=1)
    uom_code = models.CharField(max_length=16, blank=True)
    bom = models.ForeignKey(MrpBom, on_delete=models.PROTECT, related_name="orders")
    routing = models.ForeignKey(
        MrpRouting, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders"
    )
    workshop = models.ForeignKey(MrpWorkshop, on_delete=models.PROTECT, related_name="orders")
    date_planned_start = models.DateTimeField(null=True, blank=True)
    date_planned_end = models.DateTimeField(null=True, blank=True)
    date_start = models.DateTimeField(null=True, blank=True)
    date_end = models.DateTimeField(null=True, blank=True)
    state = FSMField(default=STATE_DRAFT, choices=STATE_CHOICES)
    priority = models.CharField(max_length=16, choices=PRIORITY_CHOICES, default=PRIORITY_NORMAL)
    # `source_document` : reference generique vers le document d'origine
    # (ex. ligne de commande de vente future), jamais de FK vers `sales`.
    source_document_type = models.CharField(max_length=64, blank=True)
    source_document_id = models.UUIDField(null=True, blank=True)
    sale_order_line_id = models.UUIDField(null=True, blank=True)
    qty_produced = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    qty_scrapped = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    # RG-MRP-6 : cout reel (consomme a la cloture). Le cout planifie (a
    # l'ouverture) est conserve separement pour exposer l'ecart par
    # composante (matiere/facon/frais generaux), cf. services/costing.py.
    cost_material_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    cost_labor_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    cost_overhead_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    cost_total_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    cost_material_planned_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    cost_labor_planned_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    cost_overhead_planned_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    cost_total_planned_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    suspend_reason = models.TextField(blank=True)
    cancel_reason = models.TextField(blank=True)

    class Meta:
        db_table = "mrp_order"

    def __str__(self) -> str:
        return self.reference or f"(brouillon) {self.id}"

    @transition(field=state, source=STATE_DRAFT, target=STATE_CONFIRMED)
    def confirm(self) -> None:
        pass

    @transition(field=state, source=STATE_CONFIRMED, target=STATE_RESERVED)
    def reserve(self) -> None:
        pass

    @transition(field=state, source=STATE_RESERVED, target=STATE_IN_PRODUCTION)
    def start(self) -> None:
        pass

    @transition(field=state, source=STATE_IN_PRODUCTION, target=STATE_SUSPENDED)
    def suspend(self) -> None:
        pass

    @transition(field=state, source=STATE_SUSPENDED, target=STATE_IN_PRODUCTION)
    def resume(self) -> None:
        pass

    @transition(field=state, source=STATE_IN_PRODUCTION, target=STATE_QUALITY_CONTROL)
    def send_to_quality_control(self) -> None:
        pass

    @transition(field=state, source=STATE_QUALITY_CONTROL, target=STATE_DONE)
    def finish(self) -> None:
        pass

    @transition(field=state, source=STATE_DONE, target=STATE_CLOSED)
    def close(self) -> None:
        pass

    @transition(field=state, source=[STATE_DRAFT, STATE_CONFIRMED], target=STATE_CANCELLED)
    def cancel(self) -> None:
        pass


class MrpOrderComponent(BaseModel):
    order = models.ForeignKey(MrpOrder, on_delete=models.CASCADE, related_name="components")
    bom_line = models.ForeignKey(MrpBomLine, on_delete=models.PROTECT, related_name="+")
    variant_id = models.UUIDField(null=True, blank=True)
    qty_planned = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    qty_consumed = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    uom_code = models.CharField(max_length=16, blank=True)
    lot = models.CharField(max_length=64, blank=True)
    state = models.CharField(max_length=32, default="planned")
    # RG-MRP-11 : motif obligatoire quand l'ecart planifie/reel depasse le
    # seuil parametrable (defaut 5%).
    variance_reason = models.TextField(blank=True)

    class Meta:
        db_table = "mrp_order_component"

    def __str__(self) -> str:
        return f"{self.order} — {self.bom_line}"


class MrpWorkOrder(BaseModel):
    STATE_PENDING = "pending"
    STATE_IN_PROGRESS = "in_progress"
    STATE_PAUSED = "paused"
    STATE_DONE = "done"
    STATE_CHOICES = [
        (STATE_PENDING, "En attente"),
        (STATE_IN_PROGRESS, "En cours"),
        (STATE_PAUSED, "En pause"),
        (STATE_DONE, "Termine"),
    ]

    order = models.ForeignKey(MrpOrder, on_delete=models.CASCADE, related_name="work_orders")
    routing_step = models.ForeignKey(
        MrpRoutingStep, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    workcenter = models.ForeignKey(MrpWorkcenter, on_delete=models.PROTECT, related_name="+")
    sequence = models.PositiveSmallIntegerField(default=0)
    qty_planned = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    qty_done = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    qty_rejected = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    date_planned = models.DateTimeField(null=True, blank=True)
    date_start = models.DateTimeField(null=True, blank=True)
    date_end = models.DateTimeField(null=True, blank=True)
    duration_planned_min = models.PositiveIntegerField(default=0)
    duration_real_min = models.PositiveIntegerField(default=0)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_PENDING)
    operator = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "mrp_work_order"
        ordering = ["sequence"]

    def __str__(self) -> str:
        return f"{self.order} — {self.sequence}"


class MrpSubcontractOrder(BaseModel):
    """RG-MRP-8 : l'envoi de matiere a un sous-traitant genere un mouvement
    de stock vers un emplacement virtuel « chez le sous-traitant » (futur
    module `stocks`, non construit — le mouvement de stock lui-meme sera
    branche via `stocks.services.public` quand ce module existera ; cette
    entite MRP trace deja l'operation cote production)."""

    STATE_SENT = "sent"
    STATE_RECEIVED = "received"
    STATE_CHOICES = [
        (STATE_SENT, "Envoye"),
        (STATE_RECEIVED, "Recu"),
    ]

    order = models.ForeignKey(MrpOrder, on_delete=models.CASCADE, related_name="subcontract_orders")
    partner_id = models.UUIDField()
    operation = models.ForeignKey(
        MrpOperation, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    qty = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    price_unit = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    date_sent = models.DateField(null=True, blank=True)
    date_expected = models.DateField(null=True, blank=True)
    date_received = models.DateField(null=True, blank=True)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_SENT)
    qty_received = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    qty_rejected = models.DecimalField(max_digits=18, decimal_places=4, default=0)

    class Meta:
        db_table = "mrp_subcontract_order"

    def __str__(self) -> str:
        return f"{self.order} — sous-traitance {self.partner_id}"
