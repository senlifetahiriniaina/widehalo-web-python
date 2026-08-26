"""Coeur comptable (Lot 2, phase 1) : plan comptable PCG 2005, exercices et
periodes, journaux, ecritures en partie double. La TVA/regimes fiscaux sont
ajoutes a l'etape A3 (le champ `tax` d'AccMoveLine y sera ajoute)."""

from __future__ import annotations

from django.db import models
from django_fsm import FSMField, transition

from apps.core.models.base import BaseModel, ReferenceMixin


class AccFiscalYear(BaseModel):
    STATE_OPEN = "open"
    STATE_CLOSING = "closing"
    STATE_CLOSED = "closed"
    STATE_CHOICES = [
        (STATE_OPEN, "Ouvert"),
        (STATE_CLOSING, "En cloture"),
        (STATE_CLOSED, "Cloture"),
    ]

    code = models.CharField(max_length=16)
    date_start = models.DateField()
    date_end = models.DateField()
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_OPEN)

    class Meta:
        db_table = "acc_fiscal_year"

    def __str__(self) -> str:
        return self.code


class AccPeriod(BaseModel):
    STATE_OPEN = "open"
    STATE_CLOSED = "closed"
    STATE_CHOICES = [
        (STATE_OPEN, "Ouverte"),
        (STATE_CLOSED, "Close"),
    ]

    fiscal_year = models.ForeignKey(AccFiscalYear, on_delete=models.CASCADE, related_name="periods")
    code = models.CharField(max_length=16)
    date_start = models.DateField()
    date_end = models.DateField()
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_OPEN)

    class Meta:
        db_table = "acc_period"

    def __str__(self) -> str:
        return self.code


class AccAccount(BaseModel):
    TYPE_ASSET = "asset"
    TYPE_LIABILITY = "liability"
    TYPE_EQUITY = "equity"
    TYPE_INCOME = "income"
    TYPE_EXPENSE = "expense"
    TYPE_RECEIVABLE = "receivable"
    TYPE_PAYABLE = "payable"
    TYPE_BANK = "bank"
    TYPE_CASH = "cash"
    TYPE_TAX = "tax"
    TYPE_STOCK = "stock"
    TYPE_CHOICES = [
        (TYPE_ASSET, "Actif"),
        (TYPE_LIABILITY, "Passif"),
        (TYPE_EQUITY, "Capitaux propres"),
        (TYPE_INCOME, "Produit"),
        (TYPE_EXPENSE, "Charge"),
        (TYPE_RECEIVABLE, "Creance"),
        (TYPE_PAYABLE, "Dette"),
        (TYPE_BANK, "Banque"),
        (TYPE_CASH, "Caisse"),
        (TYPE_TAX, "Taxe"),
        (TYPE_STOCK, "Stock"),
    ]

    code = models.CharField(max_length=20)
    name = models.CharField(max_length=200)
    account_class = models.PositiveSmallIntegerField(help_text="Classe PCG, 1 a 7")
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children"
    )
    type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    reconcilable = models.BooleanField(default=False)
    currency = models.CharField(max_length=3, default="MGA")
    is_active = models.BooleanField(default=True)
    # RG-ACC-9 : distribution analytique obligatoire (somme = 100%) sur les
    # lignes portees par ce compte — configurable par compte, cf. etape A6.
    analytic_required = models.BooleanField(default=False)

    class Meta:
        db_table = "acc_account"
        indexes = [models.Index(fields=["code"])]

    def __str__(self) -> str:
        return f"{self.code} {self.name}"


class AccJournal(BaseModel):
    TYPE_SALE = "sale"
    TYPE_PURCHASE = "purchase"
    TYPE_BANK = "bank"
    TYPE_CASH = "cash"
    TYPE_MISC = "misc"
    TYPE_PAYROLL = "payroll"
    TYPE_STOCK = "stock"
    TYPE_CHOICES = [
        (TYPE_SALE, "Ventes"),
        (TYPE_PURCHASE, "Achats"),
        (TYPE_BANK, "Banque"),
        (TYPE_CASH, "Caisse"),
        (TYPE_MISC, "Operations diverses"),
        (TYPE_PAYROLL, "Paie"),
        (TYPE_STOCK, "Stock"),
    ]

    code = models.CharField(max_length=16)
    name = models.CharField(max_length=120)
    type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    default_account = models.ForeignKey(
        AccAccount, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    sequence_prefix = models.CharField(max_length=16)
    currency = models.CharField(max_length=3, default="MGA")

    class Meta:
        db_table = "acc_journal"

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class AccMove(BaseModel, ReferenceMixin):
    """Une ecriture comptable. `reference` (cf. `ReferenceMixin`) reste vide
    tant que l'ecriture est en brouillon — RG-ACC-3 : elle n'est attribuee
    qu'a la publication, jamais au brouillon. Immuable en base une fois
    `state=posted` (trigger Postgres, cf. migration 0002) : toute correction
    passe par une nouvelle ecriture d'extourne (`reverses`), jamais par une
    modification de l'ecriture d'origine (RG-ACC-2)."""

    STATE_DRAFT = "draft"
    STATE_POSTED = "posted"
    STATE_CANCELLED = "cancelled"
    STATE_CHOICES = [
        (STATE_DRAFT, "Brouillon"),
        (STATE_POSTED, "Publiee"),
        (STATE_CANCELLED, "Annulee"),
    ]

    TYPE_ENTRY = "entry"
    TYPE_CUSTOMER_INVOICE = "customer_invoice"
    TYPE_CUSTOMER_CREDIT_NOTE = "customer_credit_note"
    TYPE_SUPPLIER_INVOICE = "supplier_invoice"
    TYPE_SUPPLIER_CREDIT_NOTE = "supplier_credit_note"
    TYPE_CHOICES = [
        (TYPE_ENTRY, "Ecriture diverse"),
        (TYPE_CUSTOMER_INVOICE, "Facture client"),
        (TYPE_CUSTOMER_CREDIT_NOTE, "Avoir client"),
        (TYPE_SUPPLIER_INVOICE, "Facture fournisseur"),
        (TYPE_SUPPLIER_CREDIT_NOTE, "Avoir fournisseur"),
    ]

    # Statut METIER de la facture (§5.1.5) — INDEPENDANT du `state`
    # comptable ci-dessus : `state` regit l'immuabilite/numerotation
    # (RG-ACC-1..4), `invoice_state` continue d'evoluer (paiements) meme
    # une fois la facture publiee (`state="posted"`). Le trigger
    # d'immuabilite (migration 0005) l'autorise explicitement.
    INVOICE_STATE_DRAFT = "draft"
    INVOICE_STATE_TO_VALIDATE = "to_validate"
    INVOICE_STATE_VALIDATED = "validated"
    INVOICE_STATE_PAID_PARTIALLY = "paid_partially"
    INVOICE_STATE_PAID = "paid"
    INVOICE_STATE_CANCELLED = "cancelled"
    INVOICE_STATE_OVERDUE = "overdue"
    INVOICE_STATE_IN_DISPUTE = "in_dispute"
    INVOICE_STATE_CHOICES = [
        (INVOICE_STATE_DRAFT, "Brouillon"),
        (INVOICE_STATE_TO_VALIDATE, "A valider"),
        (INVOICE_STATE_VALIDATED, "Validee"),
        (INVOICE_STATE_PAID_PARTIALLY, "Payee partiellement"),
        (INVOICE_STATE_PAID, "Payee"),
        (INVOICE_STATE_CANCELLED, "Annulee"),
        (INVOICE_STATE_OVERDUE, "En retard"),
        (INVOICE_STATE_IN_DISPUTE, "En contentieux"),
    ]

    journal = models.ForeignKey(AccJournal, on_delete=models.PROTECT, related_name="moves")
    period = models.ForeignKey(AccPeriod, on_delete=models.PROTECT, related_name="moves")
    date = models.DateField()
    # Jamais de FK Django vers `apps.partners.models.Partner` (regle de
    # couplage n°1) — un tiers est reference par son UUID uniquement.
    partner_id = models.UUIDField(null=True, blank=True)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_DRAFT)
    move_type = models.CharField(max_length=24, choices=TYPE_CHOICES, default=TYPE_ENTRY)
    invoice_state = FSMField(default=INVOICE_STATE_DRAFT, choices=INVOICE_STATE_CHOICES)
    narration = models.TextField(blank=True)
    currency = models.CharField(max_length=3, default="MGA")
    exchange_rate = models.DecimalField(max_digits=18, decimal_places=6, default=1)
    total_debit = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    total_credit = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    reverses = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversed_by_set"
    )

    class Meta:
        db_table = "acc_move"
        indexes = [models.Index(fields=["journal", "period", "state"])]
        permissions = [
            ("validate_accmove", "Peut valider une ecriture/facture"),
            ("cancel_accmove", "Peut annuler une facture avant paiement"),
        ]

    def __str__(self) -> str:
        return self.reference or f"(brouillon) {self.id}"

    @transition(field=invoice_state, source=INVOICE_STATE_DRAFT, target=INVOICE_STATE_TO_VALIDATE)
    def submit_for_validation(self) -> None:
        pass

    @transition(
        field=invoice_state,
        source=INVOICE_STATE_TO_VALIDATE,
        target=INVOICE_STATE_VALIDATED,
        permission="accounting.validate_accmove",
    )
    def validate(self) -> None:
        pass

    @transition(
        field=invoice_state,
        source=[INVOICE_STATE_DRAFT, INVOICE_STATE_TO_VALIDATE],
        target=INVOICE_STATE_CANCELLED,
        permission="accounting.cancel_accmove",
    )
    def cancel(self) -> None:
        pass

    @transition(
        field=invoice_state,
        source=[INVOICE_STATE_VALIDATED, INVOICE_STATE_OVERDUE],
        target=INVOICE_STATE_PAID_PARTIALLY,
    )
    def mark_paid_partially(self) -> None:
        pass

    @transition(
        field=invoice_state,
        source=[INVOICE_STATE_VALIDATED, INVOICE_STATE_PAID_PARTIALLY, INVOICE_STATE_OVERDUE],
        target=INVOICE_STATE_PAID,
    )
    def mark_paid(self) -> None:
        pass

    @transition(
        field=invoice_state,
        source=[INVOICE_STATE_VALIDATED, INVOICE_STATE_PAID_PARTIALLY],
        target=INVOICE_STATE_OVERDUE,
    )
    def mark_overdue(self) -> None:
        pass

    @transition(field=invoice_state, source=INVOICE_STATE_OVERDUE, target=INVOICE_STATE_IN_DISPUTE)
    def mark_in_dispute(self) -> None:
        pass


class AccTax(BaseModel):
    """RG-ACC-5 : sur un tenant au regime synthetique, aucune AccTax n'est
    proposee ni appliquee (masquage cote service/API, cf.
    services/taxes.py)."""

    TYPE_SALE = "sale"
    TYPE_PURCHASE = "purchase"
    TYPE_CHOICES = [
        (TYPE_SALE, "Vente"),
        (TYPE_PURCHASE, "Achat"),
    ]

    code = models.CharField(max_length=16)
    name = models.CharField(max_length=120)
    type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    rate = models.DecimalField(max_digits=6, decimal_places=3)
    is_included = models.BooleanField(default=False)
    account_collected = models.ForeignKey(
        AccAccount, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    account_deductible = models.ForeignKey(
        AccAccount, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "acc_tax"

    def __str__(self) -> str:
        return f"{self.name} ({self.rate}%)"


class AccPaymentTerm(BaseModel):
    name = models.CharField(max_length=120)

    class Meta:
        db_table = "acc_payment_term"

    def __str__(self) -> str:
        return self.name


class AccPaymentTermLine(BaseModel):
    VALUE_TYPE_PERCENT = "percent"
    VALUE_TYPE_FIXED = "fixed"
    VALUE_TYPE_BALANCE = "balance"
    VALUE_TYPE_CHOICES = [
        (VALUE_TYPE_PERCENT, "Pourcentage"),
        (VALUE_TYPE_FIXED, "Montant fixe"),
        (VALUE_TYPE_BALANCE, "Solde"),
    ]

    term = models.ForeignKey(AccPaymentTerm, on_delete=models.CASCADE, related_name="lines")
    sequence = models.PositiveSmallIntegerField(default=0)
    value_type = models.CharField(max_length=16, choices=VALUE_TYPE_CHOICES)
    value = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    days = models.PositiveIntegerField(default=0)
    day_of_month = models.PositiveSmallIntegerField(null=True, blank=True)
    month_offset = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "acc_payment_term_line"
        ordering = ["sequence"]


class AccExchangeRate(BaseModel):
    currency = models.CharField(max_length=3)
    date = models.DateField()
    rate_to_mga = models.DecimalField(max_digits=18, decimal_places=6)
    source = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "acc_exchange_rate"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "currency", "date"], name="uniq_exchange_rate"
            )
        ]

    def __str__(self) -> str:
        return f"{self.currency}@{self.date} = {self.rate_to_mga} MGA"


class AccMoveLine(BaseModel):
    move = models.ForeignKey(AccMove, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(AccAccount, on_delete=models.PROTECT, related_name="+")
    partner_id = models.UUIDField(null=True, blank=True)
    label = models.CharField(max_length=255, blank=True)
    debit = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    credit = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    amount_currency = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    currency = models.CharField(max_length=3, default="MGA")
    tax = models.ForeignKey(
        AccTax, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    tax_base = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    analytic_distribution = models.JSONField(default=dict, blank=True)
    due_date = models.DateField(null=True, blank=True)
    reconciled_with = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    matching_number = models.CharField(max_length=32, blank=True, db_index=True)

    class Meta:
        db_table = "acc_move_line"
        indexes = [models.Index(fields=["account"]), models.Index(fields=["matching_number"])]

    def __str__(self) -> str:
        return f"{self.label} D{self.debit}/C{self.credit}"


class AccPayment(BaseModel, ReferenceMixin):
    DIRECTION_INBOUND = "inbound"
    DIRECTION_OUTBOUND = "outbound"
    DIRECTION_CHOICES = [
        (DIRECTION_INBOUND, "Encaissement"),
        (DIRECTION_OUTBOUND, "Decaissement"),
    ]

    METHOD_CASH = "especes"
    METHOD_TRANSFER = "virement"
    METHOD_CHECK = "cheque"
    METHOD_MOBILE_MONEY = "mobile_money"
    METHOD_PROMISSORY_NOTE = "traite"
    METHOD_COMPENSATION = "compensation"
    METHOD_CHOICES = [
        (METHOD_CASH, "Especes"),
        (METHOD_TRANSFER, "Virement"),
        (METHOD_CHECK, "Cheque"),
        (METHOD_MOBILE_MONEY, "Mobile money"),
        (METHOD_PROMISSORY_NOTE, "Traite"),
        (METHOD_COMPENSATION, "Compensation"),
    ]

    STATE_DRAFT = "draft"
    STATE_POSTED = "posted"
    STATE_CHOICES = [
        (STATE_DRAFT, "Brouillon"),
        (STATE_POSTED, "Publie"),
    ]

    partner_id = models.UUIDField(null=True, blank=True)
    journal = models.ForeignKey(AccJournal, on_delete=models.PROTECT, related_name="payments")
    date = models.DateField()
    amount = models.DecimalField(max_digits=18, decimal_places=4)
    currency = models.CharField(max_length=3, default="MGA")
    direction = models.CharField(max_length=16, choices=DIRECTION_CHOICES)
    method = models.CharField(max_length=16, choices=METHOD_CHOICES)
    reference_external = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_DRAFT)
    move = models.ForeignKey(
        AccMove, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "acc_payment"

    def __str__(self) -> str:
        return self.reference or f"(brouillon) {self.id}"


class AccPaymentAllocation(BaseModel):
    """Lettrage : montant de `payment` affecte a `move_line` (la ligne
    creance/dette soldee). RG-ACC-8 : le lettrage partiel est autorise, le
    solde residuel se lit en comparant `move_line.debit`/`credit` a la
    somme des allocations."""

    payment = models.ForeignKey(AccPayment, on_delete=models.CASCADE, related_name="allocations")
    move_line = models.ForeignKey(AccMoveLine, on_delete=models.PROTECT, related_name="allocations")
    amount = models.DecimalField(max_digits=18, decimal_places=4)

    class Meta:
        db_table = "acc_payment_allocation"

    def __str__(self) -> str:
        return f"{self.payment} -> {self.move_line} : {self.amount}"


class AccAnalyticPlan(BaseModel):
    """Un axe d'analyse (Projet, Atelier, Produit, Partenaire, Region...).
    Plusieurs plans peuvent s'appliquer simultanement a une meme ligne
    d'ecriture (cf. `AccMoveLine.analytic_distribution`, §5.1.7)."""

    code = models.CharField(max_length=32)
    name = models.CharField(max_length=100)

    class Meta:
        db_table = "acc_analytic_plan"

    def __str__(self) -> str:
        return self.name


class AccAnalyticAccount(BaseModel):
    plan = models.ForeignKey(AccAnalyticPlan, on_delete=models.CASCADE, related_name="accounts")
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=120)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children"
    )

    class Meta:
        db_table = "acc_analytic_account"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "plan", "code"], name="uniq_analytic_account")
        ]

    def __str__(self) -> str:
        return f"{self.plan.code}:{self.code}"


class AccAnalyticLine(BaseModel):
    """Ventilation materialisee d'une ligne d'ecriture sur un axe
    analytique — derivee de `AccMoveLine.analytic_distribution` (JSON de
    pourcentages par plan), cf. services/analytics.py::record_analytic_lines()."""

    analytic_account = models.ForeignKey(
        AccAnalyticAccount, on_delete=models.PROTECT, related_name="lines"
    )
    move_line = models.ForeignKey(
        AccMoveLine, on_delete=models.CASCADE, related_name="analytic_lines"
    )
    date = models.DateField()
    amount = models.DecimalField(max_digits=18, decimal_places=4)
    qty = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    uom_code = models.CharField(max_length=16, blank=True)

    class Meta:
        db_table = "acc_analytic_line"
        indexes = [models.Index(fields=["analytic_account"])]

    def __str__(self) -> str:
        return f"{self.analytic_account} : {self.amount}"
