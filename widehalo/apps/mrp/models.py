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
    # Bloc C, C5 : nomenclature agroalimentaire — seul type qui porte un
    # rendement attendu et des sous-produits/coproduits (`expected_yield_
    # pct`/`by_products` ci-dessous), consomme par la reconciliation
    # matiere de C3 (PRD-7).
    TYPE_PROCESS = "process"
    TYPE_CHOICES = [
        (TYPE_MANUFACTURE, "Fabrication"),
        (TYPE_KIT, "Kit"),
        (TYPE_SUBCONTRACT, "Sous-traitance"),
        (TYPE_PROCESS, "Process (agroalimentaire)"),
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
    # Bloc C, C5 (PRD-7) : rendement attendu du produit PRINCIPAL, en % de
    # la matiere engagee — pertinent uniquement pour type=TYPE_PROCESS,
    # valide en service (`services/bom.py::add_by_product`). Consomme par
    # la reconciliation matiere de C3.
    expected_yield_pct = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    # Sous-produits/coproduits declaratifs :
    # [{"component_template_id": "<uuid>", "label": "...",
    #   "expected_qty_pct": "12.50", "is_coproduct": true}, ...].
    # JSONField plutot qu'un modele dedie — budget de modeles a 290/290
    # (zero marge, cf. tests/architecture/test_budget.py), meme patron
    # que `CatalogSectorSpec.attributes`/`MrpBomLine.qty_by_size`.
    # Purement declaratif : n'affecte JAMAIS `explode()`, consomme
    # uniquement par la reconciliation matiere de C3 (PRD-7).
    by_products = models.JSONField(default=list, blank=True)

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
    # Bloc C, C3 (PRD-9) : coût de sous-traitance replié dans le total à
    # la clôture — champ PLAT plutôt qu'ajouté au retour de
    # `compute_real_cost` (cf. services/costing.py) : garde cette
    # fonction indépendante de la sous-traitance, `close_order` (seul
    # point avec accès à `order.subcontract_orders`) est le bon endroit
    # pour l'agréger.
    cost_subcontracting_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    suspend_reason = models.TextField(blank=True)
    cancel_reason = models.TextField(blank=True)
    # Bloc C, C3 (PRD-7) : motif de l'écart entre matière engagée et
    # rendement attendu (produit + sous-produits + rebuts) au-delà du
    # seuil autorisé — cf. `services/costing.py::
    # check_material_reconciliation`. Vide si aucun écart n'a jamais
    # dépassé le seuil, ou si la nomenclature n'est pas de type process.
    material_reconciliation_reason = models.TextField(blank=True)
    # A2 (L4 Agro, docs/planning/2026-refonte-ux-sprints.md §5) : nom du
    # lot de sortie de production, renseigne a la cloture par
    # `services.transformation.finish_transformation_order`. Convention
    # `StkLot.name` cote `stocks` (pas de FK, regle de couplage n1) —
    # permet de retrouver la genealogie du lot (`stocks.services.public.
    # lot_genealogy_tree`) depuis l'ordre qui l'a produit.
    output_lot_name = models.CharField(max_length=64, blank=True)

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
    # Bloc C, C1 : UUID de la StkReservation active pour ce composant
    # (jamais une FK Django, regle de couplage n1) — resolue via
    # `stocks.services.public.release_stock_reservation` a la
    # cloture/annulation de l'ordre. None tant qu'aucune reservation
    # reelle n'existe (variant_id manquant, ou stock insuffisant a la
    # reservation).
    reservation_id = models.UUIDField(null=True, blank=True)

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
    de stock vers un emplacement virtuel « chez le sous-traitant ».

    Bloc C, C2 : le mouvement de stock reel est desormais branche via
    `stocks.services.public.send_to_subcontractor`/
    `receive_from_subcontractor` (`send_move_id` en garde la trace)."""

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
    # Bloc C, C2 : l'article MATIERE envoye au sous-traitant — ni
    # `order.variant_id` (le produit FINI de l'ordre, pas la matiere
    # envoyee) ni `operation` (ne porte aucune variante) ne l'identifient.
    # Fourni explicitement par l'appelant a l'envoi, persiste ici pour que
    # la reception n'ait pas a le refournir.
    variant_id = models.UUIDField(null=True, blank=True)
    qty = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    price_unit = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    date_sent = models.DateField(null=True, blank=True)
    date_expected = models.DateField(null=True, blank=True)
    date_received = models.DateField(null=True, blank=True)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_SENT)
    qty_received = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    qty_rejected = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    # Bloc C, C2 : UUID du StkMove d'envoi (jamais une FK Django, regle de
    # couplage n1) — resolu via `stocks.services.public.
    # receive_from_subcontractor` a la reception.
    send_move_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "mrp_subcontract_order"

    def __str__(self) -> str:
        return f"{self.order} — sous-traitance {self.partner_id}"


class MrpCra(BaseModel, ReferenceMixin):
    """Compte rendu d'activite (RG-MRP-9) : saisi par employe et par jour,
    circuit de validation draft->submitted->validated/rejected. Seul un CRA
    `validated` alimente le cout facon reel (cf. services/costing.py)."""

    STATE_DRAFT = "draft"
    STATE_SUBMITTED = "submitted"
    STATE_VALIDATED = "validated"
    STATE_REJECTED = "rejected"
    STATE_CHOICES = [
        (STATE_DRAFT, "Brouillon"),
        (STATE_SUBMITTED, "Soumis"),
        (STATE_VALIDATED, "Valide"),
        (STATE_REJECTED, "Rejete"),
    ]

    date = models.DateField()
    employee = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")
    workshop = models.ForeignKey(MrpWorkshop, on_delete=models.PROTECT, related_name="cra_entries")
    work_order = models.ForeignKey(
        MrpWorkOrder, null=True, blank=True, on_delete=models.SET_NULL, related_name="cra_entries"
    )
    order = models.ForeignKey(
        MrpOrder, null=True, blank=True, on_delete=models.SET_NULL, related_name="cra_entries"
    )
    hours = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    qty_done = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    qty_rejected = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    activity_type = models.CharField(max_length=64, blank=True)
    comment = models.TextField(blank=True)
    state = FSMField(default=STATE_DRAFT, choices=STATE_CHOICES)
    validated_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    validated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "mrp_cra"

    def __str__(self) -> str:
        return self.reference or f"CRA {self.employee} {self.date}"

    @transition(field=state, source=STATE_DRAFT, target=STATE_SUBMITTED)
    def submit(self) -> None:
        pass

    @transition(field=state, source=STATE_SUBMITTED, target=STATE_VALIDATED)
    def validate(self) -> None:
        pass

    @transition(field=state, source=STATE_SUBMITTED, target=STATE_REJECTED)
    def reject(self) -> None:
        pass


class MrpCri(BaseModel, ReferenceMixin):
    """Compte rendu d'intervention (RG-MRP-10) : evenement non productif
    (panne/reglage/incident qualite/formation/audit)."""

    TYPE_MAINTENANCE = "maintenance"
    TYPE_ADJUSTMENT = "reglage"
    TYPE_QUALITY_INCIDENT = "incident_qualite"
    TYPE_BREAKDOWN = "panne"
    TYPE_TRAINING = "formation"
    TYPE_AUDIT = "audit"
    TYPE_CHOICES = [
        (TYPE_MAINTENANCE, "Maintenance"),
        (TYPE_ADJUSTMENT, "Reglage"),
        (TYPE_QUALITY_INCIDENT, "Incident qualite"),
        (TYPE_BREAKDOWN, "Panne"),
        (TYPE_TRAINING, "Formation"),
        (TYPE_AUDIT, "Audit"),
    ]

    STATE_DRAFT = "draft"
    STATE_CLOSED = "closed"
    STATE_CHOICES = [
        (STATE_DRAFT, "Ouvert"),
        (STATE_CLOSED, "Cloture"),
    ]

    date = models.DateField()
    type = models.CharField(max_length=24, choices=TYPE_CHOICES)
    workcenter = models.ForeignKey(
        MrpWorkcenter, on_delete=models.PROTECT, related_name="cri_entries"
    )
    order = models.ForeignKey(
        MrpOrder, null=True, blank=True, on_delete=models.SET_NULL, related_name="cri_entries"
    )
    # Intervenant interne (employe) OU externe (sous-traitant/prestataire,
    # jamais de FK vers `partners`).
    intervenant_user = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    intervenant_partner_id = models.UUIDField(null=True, blank=True)
    duration_min = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True)
    cause = models.TextField(blank=True)
    action_taken = models.TextField(blank=True)
    cost_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    downtime_min = models.PositiveIntegerField(default=0)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_DRAFT)
    # Documents joints : references generiques vers `core.Document`, jamais
    # de FK directe (couplage generique deja etabli au Lot 1).
    attachments = models.JSONField(default=list, blank=True)
    # RG-PAT-8 : un incident de conformite constate en production ouvre un
    # CRI rattache au patron d'origine — UUID simple vers
    # `apps.patronage.models.PatPattern`, jamais de FK (patronage depend de
    # mrp, jamais l'inverse).
    pattern_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "mrp_cri"

    def __str__(self) -> str:
        return self.reference or f"CRI {self.workcenter} {self.date}"


class MrpScrap(BaseModel):
    """RG-MRP-12 : toute quantite rebutee genere un mouvement de stock vers
    un emplacement « rebut » (futur module `stocks`) et une charge
    analytique (futur module `accounting` — analytique deja livre en Lot 2,
    a brancher via `accounting.services.public` le moment venu)."""

    order = models.ForeignKey(MrpOrder, on_delete=models.CASCADE, related_name="scraps")
    variant_id = models.UUIDField(null=True, blank=True)
    qty = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    reason = models.CharField(max_length=255)
    cost_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    date = models.DateField()
    declared_by = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "mrp_scrap"

    def __str__(self) -> str:
        return f"{self.order} — rebut {self.qty}"


class MrpBomLineState(BaseModel):
    """MRP-FSM1 (enrichissement WideHalo) : machine a etats de suivi
    d'approvisionnement par composant d'ordre, INDEPENDANTE de l'etat de
    l'ordre de fabrication lui-meme (`MrpOrder.state`) — rend visible ce qui
    bloque une production, composant par composant."""

    STATE_TO_ORDER = "a_commander"
    STATE_SAMPLE_REQUESTED = "echantillon_demande"
    STATE_SAMPLE_EVALUATED = "echantillon_evalue"
    STATE_SUPPLIER_VALIDATED = "fournisseur_valide"
    STATE_ORDERED = "commande"
    STATE_RECEIVED = "recue"
    STATE_QUALITY_CONTROL = "controle_qualite"
    STATE_AVAILABLE = "disponible"
    STATE_IN_PRODUCTION = "en_production"
    STATE_CONSUMED = "consommee"
    STATE_SHORTAGE = "rupture"
    STATE_REJECTED = "rejetee"
    STATE_CHOICES = [
        (STATE_TO_ORDER, "A commander"),
        (STATE_SAMPLE_REQUESTED, "Echantillon demande"),
        (STATE_SAMPLE_EVALUATED, "Echantillon evalue"),
        (STATE_SUPPLIER_VALIDATED, "Fournisseur valide"),
        (STATE_ORDERED, "Commande"),
        (STATE_RECEIVED, "Recue"),
        (STATE_QUALITY_CONTROL, "Controle qualite"),
        (STATE_AVAILABLE, "Disponible"),
        (STATE_IN_PRODUCTION, "En production"),
        (STATE_CONSUMED, "Consommee"),
        (STATE_SHORTAGE, "Rupture"),
        (STATE_REJECTED, "Rejetee"),
    ]

    order_component = models.OneToOneField(
        MrpOrderComponent, on_delete=models.CASCADE, related_name="procurement_state"
    )
    state = FSMField(default=STATE_TO_ORDER, choices=STATE_CHOICES)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "mrp_bom_line_state"

    def __str__(self) -> str:
        return f"{self.order_component} — {self.state}"

    @transition(field=state, source=STATE_TO_ORDER, target=STATE_SAMPLE_REQUESTED)
    def request_sample(self) -> None:
        pass

    @transition(field=state, source=STATE_SAMPLE_REQUESTED, target=STATE_SAMPLE_EVALUATED)
    def evaluate_sample(self) -> None:
        pass

    @transition(
        field=state,
        source=[STATE_TO_ORDER, STATE_SAMPLE_EVALUATED],
        target=STATE_SUPPLIER_VALIDATED,
    )
    def validate_supplier(self) -> None:
        pass

    @transition(field=state, source=STATE_SUPPLIER_VALIDATED, target=STATE_ORDERED)
    def order(self) -> None:
        pass

    @transition(field=state, source=STATE_ORDERED, target=STATE_RECEIVED)
    def receive(self) -> None:
        pass

    @transition(field=state, source=STATE_ORDERED, target=STATE_SHORTAGE)
    def declare_shortage(self) -> None:
        pass

    @transition(field=state, source=STATE_RECEIVED, target=STATE_QUALITY_CONTROL)
    def send_to_quality_control(self) -> None:
        pass

    @transition(field=state, source=STATE_QUALITY_CONTROL, target=STATE_AVAILABLE)
    def approve(self) -> None:
        pass

    @transition(field=state, source=STATE_QUALITY_CONTROL, target=STATE_REJECTED)
    def reject(self) -> None:
        pass

    @transition(field=state, source=STATE_AVAILABLE, target=STATE_IN_PRODUCTION)
    def start_production(self) -> None:
        pass

    @transition(field=state, source=STATE_IN_PRODUCTION, target=STATE_CONSUMED)
    def consume(self) -> None:
        pass


class MrpSupplierEvaluation(BaseModel):
    """MRP-QQCD1 (enrichissement WideHalo) : evaluation fournisseur ponderee
    sur 5 criteres avant tout approvisionnement d'un composant critique.
    Ponderations par defaut issues du CDC, parametrables par tenant."""

    DEFAULT_WEIGHT_QUANTITY = 18
    DEFAULT_WEIGHT_QUALITY = 30
    DEFAULT_WEIGHT_COST = 27
    DEFAULT_WEIGHT_DELAY = 13
    DEFAULT_WEIGHT_CONFORMITY = 12

    partner_id = models.UUIDField()
    component_template_id = models.UUIDField(null=True, blank=True)
    date = models.DateField()
    # Notes brutes sur 5 (avant ponderation).
    score_quantity = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    score_quality = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    score_cost = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    score_delay = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    score_conformity = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    weight_quantity = models.PositiveSmallIntegerField(default=DEFAULT_WEIGHT_QUANTITY)
    weight_quality = models.PositiveSmallIntegerField(default=DEFAULT_WEIGHT_QUALITY)
    weight_cost = models.PositiveSmallIntegerField(default=DEFAULT_WEIGHT_COST)
    weight_delay = models.PositiveSmallIntegerField(default=DEFAULT_WEIGHT_DELAY)
    weight_conformity = models.PositiveSmallIntegerField(default=DEFAULT_WEIGHT_CONFORMITY)
    # Vrai si une certification obligatoire manque ou est expiree — bloque
    # l'approvisionnement quel que soit le score pondere.
    conformity_blocking = models.BooleanField(default=False)
    weighted_score = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "mrp_supplier_evaluation"

    def __str__(self) -> str:
        return f"Fournisseur {self.partner_id} — {self.date}"


class MrpSampleRequest(BaseModel):
    """MRP-ECH1 (enrichissement WideHalo) : demande d'echantillon fournisseur
    precedant la commande d'une nouvelle matiere (indispensable en textile
    ou la matiere se valide au toucher)."""

    STATE_REQUESTED = "requested"
    STATE_RECEIVED = "received"
    STATE_EVALUATED = "evaluated"
    STATE_APPROVED = "approved"
    STATE_REJECTED = "rejected"
    STATE_CHOICES = [
        (STATE_REQUESTED, "Demande"),
        (STATE_RECEIVED, "Recu"),
        (STATE_EVALUATED, "Evalue"),
        (STATE_APPROVED, "Approuve"),
        (STATE_REJECTED, "Rejete"),
    ]

    partner_id = models.UUIDField()
    component_template_id = models.UUIDField()
    date_requested = models.DateField()
    date_received = models.DateField(null=True, blank=True)
    evaluation_notes = models.TextField(blank=True)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_REQUESTED)

    class Meta:
        db_table = "mrp_sample_request"

    def __str__(self) -> str:
        return f"Echantillon {self.component_template_id} — {self.partner_id}"


class MrpMaintenancePlan(BaseModel):
    """MRP-GMAO1 (enrichissement WideHalo) : GMAO minimale — plan de
    maintenance preventive par declencheur calendaire ou horaire. Le calcul
    MTBF/MTTR se derive des `MrpCri` de type `panne`/`maintenance` sur le
    poste (cf. services/maintenance.py), pas stocke ici."""

    TRIGGER_CALENDAR = "calendar"
    TRIGGER_HOURS = "hours"
    TRIGGER_CHOICES = [
        (TRIGGER_CALENDAR, "Calendaire"),
        (TRIGGER_HOURS, "Horaire (heures machine)"),
    ]

    workcenter = models.ForeignKey(
        MrpWorkcenter, on_delete=models.CASCADE, related_name="maintenance_plans"
    )
    name = models.CharField(max_length=150)
    trigger_type = models.CharField(
        max_length=16, choices=TRIGGER_CHOICES, default=TRIGGER_CALENDAR
    )
    interval_days = models.PositiveIntegerField(null=True, blank=True)
    interval_hours = models.PositiveIntegerField(null=True, blank=True)
    last_done_at = models.DateField(null=True, blank=True)
    next_due_at = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "mrp_maintenance_plan"

    def __str__(self) -> str:
        return f"{self.workcenter} — {self.name}"
