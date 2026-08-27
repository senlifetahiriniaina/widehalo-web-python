"""Ventes (§5.5) : devis (`SalesQuotation`/`SalesQuotationLine`, S1) et
commande de vente (`SalesOrder`/`SalesOrderLine`, S2, FSM complete
§5.5.4) — cf. plan, sous-sequencement du module `sales`. La qualification
d'origine par ligne (RG-SAL-3, champ `source` ecrit des S1) est traitee a
la confirmation depuis S3 (`services.procurement.qualify_and_process_order`,
reel pour "a produire", stube pour "sur stock"/"a acheter" tant que
`stocks`/`purchase` n'existent pas). La facturation reelle (RG-SAL-2,
`billing_policy` par ligne, + SAL-AVCT1 "a l'avancement de production")
est cablee depuis S4 (`services.invoicing`). La planification periodique
(`SalesRecurrence`, RG-SAL-6) est ajoutee en S5 (`services.recurrence`) :
generation automatique d'une commande brouillon a partir d'un gabarit,
JAMAIS auto-confirmee, avec notification du commercial pour validation.
S6 ajoute les previsions (RG-SAL-7/8, SAL-SAIS1) : `SalesCustomerCalendar`
(calendrier client), `SalesTarget` (objectifs commerciaux) et
`SalesForecast` (sortie de `services.forecast.build_forecast`) ; RG-SAL-9
(incoterm obligatoire a l'export) est ferme par `SalesOrder.is_export` +
`services.orders.ensure_incoterm_for_export`.

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
    # RG-SAL-2 (S4) : cumul de ce qui a deja ete facture pour cette
    # commande (toutes lignes confondues), en MGA — sert a determiner
    # quand la commande est entierement facturee (cf.
    # `services.invoicing.invoice_order`), independamment du detail par
    # ligne (`SalesOrderLine.qty_invoiced`).
    invoiced_amount_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    # RG-SAL-9 (S6) : saisi par l'utilisateur — aucune detection automatique
    # du pays du partenaire dans ce lot (`partners.services.public` n'expose
    # pas le pays). Rend `incoterm` obligatoire (cf.
    # `services.orders.ensure_incoterm_for_export`, appelee depuis
    # `confirm_order`).
    is_export = models.BooleanField(default=False)

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

    # RG-SAL-2 (facturation reelle) : cablee depuis S4 par
    # `services.invoicing.invoice_order`, qui ne declenche cette
    # transition que lorsque `invoiced_amount_mga` couvre desormais
    # `amount_total_mga` (tolerance documentee sur `invoice_order`) —
    # une facturation partielle laisse la commande dans son etat courant.
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

    # RG-SAL-2 (§5.5.3) : politique de facturation parametrable par
    # ligne. SAL-AVCT1 (§5.5.9) ajoute le 4e mode "a l'avancement de
    # production", uniquement pertinent pour une ligne `source=
    # "production"` ayant un `mrp_order_id` reel (branche reelle de
    # RG-SAL-3, jamais les stubs "sur stock"/"a acheter").
    BILLING_ON_ORDERED_QTY = "on_ordered_qty"
    BILLING_ON_DELIVERED_QTY = "on_delivered_qty"
    BILLING_ON_DEPOSIT = "on_deposit"
    BILLING_ON_PRODUCTION_PROGRESS = "on_production_progress"
    BILLING_POLICY_CHOICES = [
        (BILLING_ON_ORDERED_QTY, "Sur quantite commandee"),
        (BILLING_ON_DELIVERED_QTY, "Sur quantite livree"),
        (BILLING_ON_DEPOSIT, "Sur acompte"),
        (BILLING_ON_PRODUCTION_PROGRESS, "A l'avancement de production"),
    ]

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
    billing_policy = models.CharField(
        max_length=24, choices=BILLING_POLICY_CHOICES, default=BILLING_ON_ORDERED_QTY
    )
    # Uniquement significatif quand `billing_policy == BILLING_ON_DEPOSIT`
    # (ex. 30.00 pour un acompte de 30% a la commande). Nul sinon.
    deposit_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = "sales_order_line"
        ordering = ["sequence"]

    def __str__(self) -> str:
        return f"{self.description} x{self.qty}"


class SalesRecurrence(BaseModel):
    """Planification periodique (§5.5.2/5.5.3, S5, RG-SAL-6) : gabarit de
    generation automatique de commandes brouillon. Pas de `ReferenceMixin`
    — ce n'est pas un document commercial mais un enregistrement de
    configuration (meme categorie que `CrmPipeline`), donc aucune
    `reference` sequentielle a lui attribuer.

    `day_rule` reste une metadonnee informative en S5, jamais parsee par
    une logique de calendrier complexe : c'est une simple chaine libre
    documentant a l'humain quel jour dans l'intervalle declenche la
    generation (ex. "first_monday", "last_day_of_month", ou un simple
    entier textuel type "15" pour le 15 du mois) — la date reelle qui
    pilote la generation est `next_run`, avancee automatiquement par
    `services.recurrence.generate_due_order` selon `interval` uniquement
    (le mecanisme ne lit jamais `day_rule` pour calculer une date, il ne
    sert qu'a etre affiche/documente aupres du commercial)."""

    INTERVAL_WEEKLY = "weekly"
    INTERVAL_MONTHLY = "monthly"
    INTERVAL_QUARTERLY = "quarterly"
    INTERVAL_YEARLY = "yearly"
    INTERVAL_CHOICES = [
        (INTERVAL_WEEKLY, "Hebdomadaire"),
        (INTERVAL_MONTHLY, "Mensuel"),
        (INTERVAL_QUARTERLY, "Trimestriel"),
        (INTERVAL_YEARLY, "Annuel"),
    ]

    name = models.CharField(max_length=150)
    interval = models.CharField(max_length=16, choices=INTERVAL_CHOICES)
    day_rule = models.CharField(max_length=64, blank=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    next_run = models.DateField()
    # La commande gabarit dont les donnees/lignes sont recopiees a chaque
    # generation (cf. `services.recurrence.generate_due_order`) — vraie FK
    # Django car `SalesOrder` appartient au meme module `sales` (pas une
    # reference inter-app, la regle de couplage n1 ne s'applique pas ici).
    # `PROTECT` : un gabarit encore utilise par une recurrence ne doit
    # jamais pouvoir etre supprime silencieusement.
    template_order = models.ForeignKey(
        SalesOrder, on_delete=models.PROTECT, related_name="recurrences_using_as_template"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "sales_recurrence"

    def __str__(self) -> str:
        return self.name


class SalesCustomerCalendar(BaseModel):
    """Calendrier client (§5.5.3, RG-SAL-7) : fermetures/pics saisonniers
    connus d'un partenaire, consommes par `services.forecast.
    customer_calendar_adjustment` pour ajuster une prevision par
    periode. Pas de `ReferenceMixin` — enregistrement de configuration,
    meme categorie que `SalesRecurrence`, aucune reference sequentielle."""

    TYPE_CLOSURE = "closure"
    TYPE_PEAK_ACTIVITY = "peak_activity"
    TYPE_CAMPAIGN = "campaign"
    TYPE_INVENTORY = "inventory"
    TYPE_CHOICES = [
        (TYPE_CLOSURE, "Fermeture"),
        (TYPE_PEAK_ACTIVITY, "Pic d'activite"),
        (TYPE_CAMPAIGN, "Campagne"),
        (TYPE_INVENTORY, "Inventaire"),
    ]

    # Jamais de FK Django vers `apps.partners.models.Partner` (regle de
    # couplage n1).
    partner_id = models.UUIDField()
    label = models.CharField(max_length=150)
    date_from = models.DateField()
    date_to = models.DateField()
    type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    # Modificateur applique a la demande prevue du partenaire sur la
    # periode (ex. +50.00 pour un pic, -100.00 pour une fermeture totale).
    impact_pct = models.DecimalField(max_digits=6, decimal_places=2)

    class Meta:
        db_table = "sales_customer_calendar"

    def __str__(self) -> str:
        return f"{self.label} ({self.date_from} -> {self.date_to})"


class SalesTarget(BaseModel):
    """Objectif commercial (§5.5.3) : `period` est une simple chaine de
    bucket mensuel (ex. "2026-01"), pas une FK vers
    `apps.accounting.models.AccPeriod` — cette derniere est une periode
    fiscale comptable reelle (cloture/lettrage), un couplage bien trop
    fort pour un objectif commercial qui n'a besoin que d'un bucket
    d'affichage. Pas de `ReferenceMixin` — enregistrement de
    configuration, pas un document commercial."""

    SCOPE_COMPANY = "company"
    SCOPE_TEAM = "team"
    SCOPE_SALESPERSON = "salesperson"
    SCOPE_CHOICES = [
        (SCOPE_COMPANY, "Entreprise"),
        (SCOPE_TEAM, "Equipe"),
        (SCOPE_SALESPERSON, "Commercial"),
    ]

    period = models.CharField(max_length=7)
    scope = models.CharField(max_length=16, choices=SCOPE_CHOICES, default=SCOPE_COMPANY)
    # UUID d'equipe (`apps.crm.models.CrmTeam`) ou de commercial
    # (`core.User`) selon `scope` — jamais de FK, nul quand `scope ==
    # "company"`.
    scope_ref = models.UUIDField(null=True, blank=True)
    amount_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    qty = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)

    class Meta:
        db_table = "sales_target"

    def __str__(self) -> str:
        return f"{self.scope}:{self.period}"


class SalesForecast(BaseModel):
    """Prevision produit x periode (RG-SAL-7/8, SAL-SAIS1, S6) — sortie de
    `services.forecast.build_forecast`. Pas de `ReferenceMixin` : c'est un
    resultat de calcul recomputable, pas un document commercial numerote."""

    CONFIDENCE_LOW = "low"
    CONFIDENCE_MEDIUM = "medium"
    CONFIDENCE_HIGH = "high"
    CONFIDENCE_CHOICES = [
        (CONFIDENCE_LOW, "Faible"),
        (CONFIDENCE_MEDIUM, "Moyenne"),
        (CONFIDENCE_HIGH, "Haute"),
    ]

    period = models.CharField(max_length=7)
    variant_id = models.UUIDField()
    # Nul = prevision produit tous clients confondus, renseigne = prevision
    # restreinte a un partenaire (cf. `customer_calendar_adjustment`).
    partner_id = models.UUIDField(null=True, blank=True)
    qty_forecast = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    # Renseigne a posteriori une fois la periode cloturee — jamais calcule
    # par ce lot (cf. plan, hors-perimetre S6).
    qty_actual = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    confidence = models.CharField(max_length=8, choices=CONFIDENCE_CHOICES, default=CONFIDENCE_LOW)
    # Code court identifiant la methode ayant produit `qty_forecast` (ex.
    # "weighted_moving_average+exponential_smoothing") — RG-SAL-8
    # (explicabilite).
    method = models.CharField(max_length=64, blank=True)
    computed_at = models.DateTimeField(auto_now=True)
    # RG-SAL-8 : tous les intrants/sorties intermediaires du calcul, pour
    # qu'un humain puisse reconstituer *pourquoi* `qty_forecast`/
    # `dominant_cause` valent ce qu'ils valent — jamais un modele boite
    # noire.
    parameters = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "sales_forecast"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "period", "variant_id", "partner_id"],
                name="uniq_sales_forecast_tenant_period_variant_partner",
            )
        ]

    def __str__(self) -> str:
        return f"{self.variant_id}@{self.period}"
