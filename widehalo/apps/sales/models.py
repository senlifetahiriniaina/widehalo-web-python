"""Ventes (§5.5) : devis (`SalesQuotation`/`SalesQuotationLine`, S1) et
commande de vente (`SalesOrder`/`SalesOrderLine`, S2, FSM complete
§5.5.4) — cf. plan, sous-sequencement du module `sales`. La qualification
d'origine par ligne (RG-SAL-3, champ `source` ecrit des S1) est traitee a
la confirmation depuis S3 (`services.procurement.qualify_and_process_order`,
reel pour "a produire", stube pour "sur stock"/"a acheter" tant que
`stocks`/`purchase` n'existent pas), la facturation reelle (RG-SAL-2) est
differee a S4, la recurrence a S5.

Regle de couplage n1 : `sales` ne fait jamais de FK Django vers
`apps.partners`/`apps.catalog`/`apps.crm`/`apps.accounting`/`apps.mrp` —
ces entites sont referencees par UUID nu, resolues via `services.public`
de chaque app quand une information affichable (reference, prix...) est
necessaire."""

from __future__ import annotations

from django.db import models
from django_fsm import FSMField, transition

from apps.core.models.base import BaseModel, ReferenceMixin


class SalesQuotation(BaseModel, ReferenceMixin):
    STATE_DRAFT = "draft"
    STATE_SENT = "sent"
    STATE_ACCEPTED = "accepted"
    STATE_DECLINED = "declined"
    STATE_EXPIRED = "expired"
    STATE_CHOICES = [
        (STATE_DRAFT, "Brouillon"),
        (STATE_SENT, "Envoye"),
        (STATE_ACCEPTED, "Accepte"),
        (STATE_DECLINED, "Refuse"),
        (STATE_EXPIRED, "Expire"),
    ]

    INCOTERM_EXW = "EXW"
    INCOTERM_FOB = "FOB"
    INCOTERM_CIF = "CIF"
    INCOTERM_DAP = "DAP"
    INCOTERM_DDP = "DDP"
    INCOTERM_CHOICES = [
        (INCOTERM_EXW, "EXW — A l'usine"),
        (INCOTERM_FOB, "FOB — Franco a bord"),
        (INCOTERM_CIF, "CIF — Cout, assurance et fret"),
        (INCOTERM_DAP, "DAP — Rendu au lieu de destination"),
        (INCOTERM_DDP, "DDP — Rendu droits acquittes"),
    ]

    # Jamais de FK Django vers `apps.partners.models.Partner` (regle de
    # couplage n1) — un tiers est reference par son UUID uniquement.
    partner_id = models.UUIDField()
    contact = models.CharField(max_length=150, blank=True)
    # Lien de tracabilite en lecture seule vers `apps.crm.models.CrmLead`,
    # jamais une FK : `sales` n'importe et ne mute jamais l'etat d'un lead
    # CRM (cf. plan, decision de couplage minimal RG-CRM-4/RG-SAL).
    source_lead_id = models.UUIDField(null=True, blank=True)
    date = models.DateField()
    validity_date = models.DateField(null=True, blank=True)
    # Jamais de FK Django vers `apps.catalog.models.PriceList`.
    pricelist_id = models.UUIDField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="MGA")
    # Jamais de FK Django vers `apps.accounting.models.AccPaymentTerm` —
    # purement informatif en S1, pas encore applique/valide (S4).
    payment_term_id = models.UUIDField(null=True, blank=True)
    incoterm = models.CharField(max_length=8, choices=INCOTERM_CHOICES, blank=True)
    delivery_address = models.TextField(blank=True)
    salesperson = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_DRAFT)
    amount_untaxed = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    amount_tax = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    amount_total = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    amount_total_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    notes = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)

    class Meta:
        db_table = "sales_quotation"

    def __str__(self) -> str:
        return self.reference or str(self.id)


class SalesQuotationLine(BaseModel):
    SOURCE_STOCK = "stock"
    SOURCE_PRODUCTION = "production"
    SOURCE_ACHAT = "achat"
    SOURCE_CHOICES = [
        (SOURCE_STOCK, "Sur stock"),
        (SOURCE_PRODUCTION, "A produire"),
        (SOURCE_ACHAT, "A acheter"),
    ]

    quotation = models.ForeignKey(SalesQuotation, on_delete=models.CASCADE, related_name="lines")
    sequence = models.PositiveIntegerField(default=0)
    # Jamais de FK Django vers `apps.catalog.models.ProductVariant` — un
    # article est reference par son UUID, resolu via `catalog.services.public`.
    # Nullable pour autoriser les lignes hors catalogue (`is_custom`).
    variant_id = models.UUIDField(null=True, blank=True)
    is_custom = models.BooleanField(default=False)
    description = models.CharField(max_length=255)
    qty = models.DecimalField(max_digits=18, decimal_places=4, default=1)
    uom = models.CharField(max_length=16, blank=True)
    unit_price = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    # Jamais de FK Django vers `apps.accounting.models.AccTax` — purement
    # informatif en S1, aucun calcul de taxe n'est encore effectue.
    tax_id = models.UUIDField(null=True, blank=True)
    subtotal = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    # Renseignes plus tard par `mrp.services.public.simulate_product_cost`
    # (gap identifie pour un lot ulterieur) — toujours nuls en S1.
    cost_estimate_mga = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    margin_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    lead_time_days = models.PositiveIntegerField(null=True, blank=True)
    # RG-SAL-3 (qualification d'origine par ligne) : le champ est ecrit des
    # S1 mais sa logique de traitement (declenchement OF/reservation stock/
    # demande d'achat) est differee a S3 (cf. plan).
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default=SOURCE_STOCK)

    class Meta:
        db_table = "sales_quotation_line"
        ordering = ["sequence"]

    def __str__(self) -> str:
        return f"{self.description} x{self.qty}"


class SalesOrder(BaseModel, ReferenceMixin):
    """Commande de vente (§5.5.2/5.5.4, S2). Reprend tous les champs du
    devis (RG-SAL-1 : chaine documentaire sans ressaisie, cf.
    `services.orders.create_order_from_quotation`) sauf `state`, remplace
    ici par une machine a etats complete (`django-fsm-2`, meme patron que
    `AccMove.invoice_state`/`MrpOrder.state`) qui couvre en un seul champ
    ce que le diagramme du CDC dessine comme trois statuts croises
    (`state`/`delivery_state`/`invoice_state`) — simplification assumee,
    volontaire : batir trois FSM distinctes pour un seul cycle de vie
    lineaire aurait surdesigne l'intention du CDC."""

    STATE_DRAFT = "draft"
    STATE_SENT = "sent"
    STATE_CONFIRMED = "confirmed"
    STATE_IN_PREPARATION = "in_preparation"
    STATE_PARTIALLY_DELIVERED = "partially_delivered"
    STATE_DELIVERED = "delivered"
    STATE_INVOICED = "invoiced"
    STATE_CLOSED = "closed"
    STATE_CANCELLED = "cancelled"
    STATE_BLOCKED = "blocked"
    STATE_CHOICES = [
        (STATE_DRAFT, "Brouillon"),
        (STATE_SENT, "Envoyee"),
        (STATE_CONFIRMED, "Confirmee"),
        (STATE_IN_PREPARATION, "En preparation"),
        (STATE_PARTIALLY_DELIVERED, "Livree partiellement"),
        (STATE_DELIVERED, "Livree"),
        (STATE_INVOICED, "Facturee"),
        (STATE_CLOSED, "Cloturee"),
        (STATE_CANCELLED, "Annulee"),
        (STATE_BLOCKED, "Bloquee"),
    ]

    INCOTERM_EXW = SalesQuotation.INCOTERM_EXW
    INCOTERM_FOB = SalesQuotation.INCOTERM_FOB
    INCOTERM_CIF = SalesQuotation.INCOTERM_CIF
    INCOTERM_DAP = SalesQuotation.INCOTERM_DAP
    INCOTERM_DDP = SalesQuotation.INCOTERM_DDP
    INCOTERM_CHOICES = SalesQuotation.INCOTERM_CHOICES

    # Chaine documentaire (RG-SAL-1) : lien optionnel vers le devis
    # d'origine — une commande peut aussi naitre directement (creation
    # directe legitime, le CDC decrit le flux devis->commande comme le
    # flux principal, pas le seul).
    quotation = models.ForeignKey(
        SalesQuotation, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders"
    )
    # Jamais de FK Django vers `apps.partners.models.Partner` (regle de
    # couplage n1) — un tiers est reference par son UUID uniquement.
    partner_id = models.UUIDField()
    contact = models.CharField(max_length=150, blank=True)
    # Lien de tracabilite en lecture seule vers `apps.crm.models.CrmLead`.
    source_lead_id = models.UUIDField(null=True, blank=True)
    date = models.DateField()
    date_confirmed = models.DateField(null=True, blank=True)
    # Date de livraison promise au client (distincte de la livraison
    # reelle, non geree ici tant que `stocks` n'existe pas).
    commitment_date = models.DateField(null=True, blank=True)
    # Jamais de FK Django vers `apps.catalog.models.PriceList`.
    pricelist_id = models.UUIDField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="MGA")
    # Jamais de FK Django vers `apps.accounting.models.AccPaymentTerm`.
    payment_term_id = models.UUIDField(null=True, blank=True)
    incoterm = models.CharField(max_length=8, choices=INCOTERM_CHOICES, blank=True)
    delivery_address = models.TextField(blank=True)
    salesperson = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    state = FSMField(default=STATE_DRAFT, choices=STATE_CHOICES)
    # Motif obligatoire d'annulation/de blocage (meme patron que
    # `MrpOrder.cancel_reason`/`suspend_reason`) — trace pour audit.
    cancel_reason = models.TextField(blank=True)
    blocked_reason = models.TextField(blank=True)
    amount_untaxed = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    amount_tax = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    amount_total = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    amount_total_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    notes = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)
    # Champ `recurrence` du CDC (§5.5.2) : seul le drapeau + le
    # placeholder d'UUID sont ecrits en S2, le vrai modele
    # `SalesRecurrence`/la logique de generation sont S5.
    is_recurring = models.BooleanField(default=False)
    recurrence_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "sales_order"

    def __str__(self) -> str:
        return self.reference or str(self.id)

    @transition(field=state, source=STATE_DRAFT, target=STATE_SENT)
    def send(self) -> None:
        pass

    @transition(field=state, source=[STATE_DRAFT, STATE_SENT], target=STATE_CONFIRMED)
    def confirm(self) -> None:
        pass

    @transition(field=state, source=[STATE_DRAFT, STATE_SENT], target=STATE_BLOCKED)
    def block_for_credit(self) -> None:
        pass

    @transition(field=state, source=STATE_BLOCKED, target=STATE_CONFIRMED)
    def unblock(self) -> None:
        pass

    @transition(field=state, source=STATE_CONFIRMED, target=STATE_IN_PREPARATION)
    def start_preparation(self) -> None:
        pass

    @transition(field=state, source=STATE_IN_PREPARATION, target=STATE_PARTIALLY_DELIVERED)
    def mark_partially_delivered(self) -> None:
        pass

    @transition(
        field=state,
        source=[STATE_IN_PREPARATION, STATE_PARTIALLY_DELIVERED],
        target=STATE_DELIVERED,
    )
    def mark_delivered(self) -> None:
        pass

    # RG-SAL-2 (facturation reelle) differee a S4 : cette transition est
    # declaree pour completude du diagramme §5.5.4 mais n'est encore
    # declenchee par aucune fonction de service reelle (cf. tests, qui
    # l'exercent directement via `attempt_transition` pour la couverture
    # d'aretes FSM, meme patron que les aretes non encore cablees de
    # `AccMove.invoice_state`).
    @transition(field=state, source=STATE_DELIVERED, target=STATE_INVOICED)
    def mark_invoiced(self) -> None:
        pass

    @transition(field=state, source=STATE_INVOICED, target=STATE_CLOSED)
    def close(self) -> None:
        pass

    @transition(
        field=state,
        source=[
            STATE_DRAFT,
            STATE_SENT,
            STATE_CONFIRMED,
            STATE_IN_PREPARATION,
            STATE_PARTIALLY_DELIVERED,
            STATE_BLOCKED,
        ],
        target=STATE_CANCELLED,
    )
    def cancel(self) -> None:
        pass


class SalesOrderLine(BaseModel):
    SOURCE_STOCK = SalesQuotationLine.SOURCE_STOCK
    SOURCE_PRODUCTION = SalesQuotationLine.SOURCE_PRODUCTION
    SOURCE_ACHAT = SalesQuotationLine.SOURCE_ACHAT
    SOURCE_CHOICES = SalesQuotationLine.SOURCE_CHOICES

    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name="lines")
    sequence = models.PositiveIntegerField(default=0)
    # Jamais de FK Django vers `apps.catalog.models.ProductVariant`.
    variant_id = models.UUIDField(null=True, blank=True)
    is_custom = models.BooleanField(default=False)
    description = models.CharField(max_length=255)
    qty = models.DecimalField(max_digits=18, decimal_places=4, default=1)
    uom = models.CharField(max_length=16, blank=True)
    unit_price = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    # Jamais de FK Django vers `apps.accounting.models.AccTax`.
    tax_id = models.UUIDField(null=True, blank=True)
    subtotal = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    cost_estimate_mga = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    margin_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    lead_time_days = models.PositiveIntegerField(null=True, blank=True)
    # RG-SAL-3 : qualification traitee a la confirmation depuis S3 (cf.
    # `services.procurement.qualify_and_process_order`).
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default=SOURCE_STOCK)
    qty_delivered = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    qty_invoiced = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    # Renseigne par la qualification RG-SAL-3 (S3) quand un `MrpOrder` reel
    # est cree pour la ligne — reste nul sinon (stock/achat/production non
    # qualifiable automatiquement).
    qty_to_produce = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    # Jamais de FK Django vers `apps.mrp.models.MrpOrder` — reference par
    # UUID nu, renseignee depuis S3 quand la branche "a produire" appelle
    # `mrp.services.public.create_manufacturing_order` (gap comble par ce
    # lot). Reste nul si aucune nomenclature/atelier actif n'est
    # disponible, ou si la ligne n'est pas qualifiee "a produire".
    mrp_order_id = models.UUIDField(null=True, blank=True)
    # Reference par UUID nu vers une future ligne de commande d'achat
    # (`apps.purchase`, module pas encore construit) — champ declare des
    # maintenant conformement au schema du CDC, reste nul indefiniment
    # tant que `purchase` n'existe pas.
    purchase_order_line_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "sales_order_line"
        ordering = ["sequence"]

    def __str__(self) -> str:
        return f"{self.description} x{self.qty}"
