"""Coeur comptable (Lot 2, phase 1) : plan comptable PCG 2005, exercices et
periodes, journaux, ecritures en partie double. La TVA/regimes fiscaux sont
ajoutes a l'etape A3 (le champ `tax` d'AccMoveLine y sera ajoute)."""

from __future__ import annotations

from decimal import Decimal

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

    FUNCTIONAL_PRODUCTION = "production"
    FUNCTIONAL_DISTRIBUTION = "distribution"
    FUNCTIONAL_ADMINISTRATION = "administration"
    FUNCTIONAL_AUTRE = "autre"
    FUNCTIONAL_DESTINATION_CHOICES = [
        (FUNCTIONAL_PRODUCTION, "Production"),
        (FUNCTIONAL_DISTRIBUTION, "Distribution"),
        (FUNCTIONAL_ADMINISTRATION, "Administration"),
        (FUNCTIONAL_AUTRE, "Autre"),
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
    # ACC-BIL (§1.10.1 du document annexe, Art. 131-3 a 131-11) : actif/passif
    # courant vs non courant. Par defaut True (la majorite des comptes du
    # cycle d'exploitation — creances, dettes, tresorerie, taxes, stocks —
    # sont courants) ; positionne explicitement a False dans la fixture
    # PCG2005 pour les immobilisations (classe 2) et les capitaux propres,
    # seules exceptions "structurelles" au sens de l'annexe. Reserve OECFM :
    # cette ventilation par defaut n'est pas validee par un expert-comptable,
    # cf. docstring de `chart_of_accounts.py`.
    is_current = models.BooleanField(default=True)
    # ACC-CR-FN1 (§1.10.2 du document annexe) : cle de ventilation
    # fonctionnelle sur les comptes de charge, permettant de reclasser les
    # memes ecritures que le compte de resultat par nature (ACC-CR) en compte
    # de resultat par fonction (ACC-CR-FCT) sans double saisie. Vide par
    # defaut (comptes non-charge — produits, bilan — non concernes) ;
    # reserve OECFM : la repartition par defaut posee dans la fixture PCG2005
    # est approximative, cf. docstring de `chart_of_accounts.py`.
    functional_destination = models.CharField(
        max_length=16, choices=FUNCTIONAL_DESTINATION_CHOICES, blank=True
    )

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


class AccTaxCalendar(BaseModel):
    """ACC-CAL1 (§1.2 du document annexe) : une echeance fiscale DGI pour ce
    tenant. Les echeances legales malgaches se deplacent au gre des
    communiques DGI — ce modele reste volontairement une simple liste de
    dates concretes par tenant (pas un moteur de regles de recurrence) :
    `due_date` porte la prochaine echeance CONNUE pour ce tenant, editable a
    tout moment par un comptable/admin quand la DGI publie un communique qui
    la deplace. `is_recurring_template=True` marque une ligne "modele" que
    `services/tax_calendar.py::seed_default_tax_calendar` peut reconduire
    d'une periode a l'autre (le tenant clone/ajuste, aucune reconduction
    automatique en V1)."""

    DECLARATION_IRSA = "irsa"
    DECLARATION_TVA = "tva"
    DECLARATION_IR_ACOMPTE = "ir_acompte"
    DECLARATION_IS_ANNUAL = "is_annual"
    DECLARATION_IR_ANNUAL = "ir_annual"
    DECLARATION_IRCM = "ircm"
    DECLARATION_DCOM = "dcom"
    DECLARATION_TVM = "tvm"
    DECLARATION_IFT = "ift"
    DECLARATION_IFPB = "ifpb"
    DECLARATION_ETATS_FINANCIERS = "etats_financiers"
    DECLARATION_TYPE_CHOICES = [
        (DECLARATION_IRSA, "IRSA"),
        (DECLARATION_TVA, "TVA"),
        (DECLARATION_IR_ACOMPTE, "Acompte IR"),
        (DECLARATION_IS_ANNUAL, "IS annuel"),
        (DECLARATION_IR_ANNUAL, "IR annuel"),
        (DECLARATION_IRCM, "IRCM"),
        (DECLARATION_DCOM, "DCOM"),
        (DECLARATION_TVM, "TVM"),
        (DECLARATION_IFT, "IFT"),
        (DECLARATION_IFPB, "IFPB"),
        (DECLARATION_ETATS_FINANCIERS, "Depot des etats financiers"),
    ]

    PERIODICITY_MONTHLY = "monthly"
    PERIODICITY_BIMONTHLY = "bimonthly"
    PERIODICITY_SEMIANNUAL = "semiannual"
    PERIODICITY_ANNUAL = "annual"
    PERIODICITY_VARIABLE = "variable"
    PERIODICITY_CHOICES = [
        (PERIODICITY_MONTHLY, "Mensuelle"),
        (PERIODICITY_BIMONTHLY, "Bimestrielle"),
        (PERIODICITY_SEMIANNUAL, "Semestrielle"),
        (PERIODICITY_ANNUAL, "Annuelle"),
        (PERIODICITY_VARIABLE, "Variable"),
    ]

    declaration_type = models.CharField(max_length=24, choices=DECLARATION_TYPE_CHOICES)
    label = models.CharField(max_length=200)
    due_date = models.DateField()
    periodicity = models.CharField(max_length=16, choices=PERIODICITY_CHOICES)
    is_recurring_template = models.BooleanField(default=False)

    class Meta:
        db_table = "acc_tax_calendar"
        indexes = [models.Index(fields=["due_date"])]

    def __str__(self) -> str:
        return f"{self.get_declaration_type_display()} — {self.due_date}"


class AccAsset(BaseModel, ReferenceMixin):
    """ACC-ANNEXE1 (§1.11 du document annexe) : une immobilisation, base de
    l'annexe "Etat de l'actif immobilise" et, via `AccAssetDepreciation", de
    l'annexe "Etat des amortissements". `category` reprend la granularite
    du document annexe ("Categorie d'immobilisation") — approximee ici aux
    3 grandes masses du PCG 2005 (incorporelles classe 20, corporelles
    classes 21-23, financieres classe 26-27) faute de sous-nomenclature plus
    fine imposee par un texte reglementaire verifie (meme reserve OECFM que
    `services/reports.py`)."""

    CATEGORY_INCORPORELLE = "incorporelle"
    CATEGORY_CORPORELLE = "corporelle"
    CATEGORY_FINANCIERE = "financiere"
    CATEGORY_CHOICES = [
        (CATEGORY_INCORPORELLE, "Immobilisation incorporelle"),
        (CATEGORY_CORPORELLE, "Immobilisation corporelle"),
        (CATEGORY_FINANCIERE, "Immobilisation financiere"),
    ]

    METHOD_LINEAIRE = "lineaire"
    METHOD_DEGRESSIF = "degressif"
    METHOD_CHOICES = [
        (METHOD_LINEAIRE, "Lineaire"),
        (METHOD_DEGRESSIF, "Degressif"),
    ]

    STATE_ACTIVE = "active"
    STATE_DISPOSED = "disposed"
    STATE_CHOICES = [
        (STATE_ACTIVE, "En service"),
        (STATE_DISPOSED, "Cedee/mise au rebut"),
    ]

    category = models.CharField(max_length=16, choices=CATEGORY_CHOICES)
    label = models.CharField(max_length=200)
    account = models.ForeignKey(AccAccount, on_delete=models.PROTECT, related_name="+")
    acquisition_date = models.DateField()
    acquisition_value_mga = models.DecimalField(max_digits=18, decimal_places=4)
    # V1 : seule la methode lineaire est implementee (cf.
    # services/assets.py::register_asset) — `degressif` reste declarable ici
    # (le champ existe et le CDC nomme les deux methodes) mais est refuse a
    # l'enregistrement, memes principes que RG-SAL-8 ("explicabilite
    # d'abord", cf. plan) : ne jamais calculer silencieusement un
    # amortissement degressif approximatif.
    depreciation_method = models.CharField(max_length=16, choices=METHOD_CHOICES)
    useful_life_years = models.PositiveIntegerField()
    residual_value_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    disposal_date = models.DateField(null=True, blank=True)
    disposal_value_mga = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_ACTIVE)

    class Meta:
        db_table = "acc_asset"

    def __str__(self) -> str:
        return self.reference or self.label


class AccAssetMovement(BaseModel):
    """Mouvement d'immobilisation (§1.11 du document annexe : "Entrees,
    sorties, virements de poste a poste par categorie"), source de l'annexe
    "Etat de l'actif immobilise" (`services/reports.py::fixed_asset_annexes`)."""

    MOVEMENT_ACQUISITION = "acquisition"
    MOVEMENT_DISPOSAL = "disposal"
    MOVEMENT_TRANSFER = "transfer"
    MOVEMENT_TYPE_CHOICES = [
        (MOVEMENT_ACQUISITION, "Acquisition"),
        (MOVEMENT_DISPOSAL, "Cession/mise au rebut"),
        (MOVEMENT_TRANSFER, "Virement de poste a poste"),
    ]

    asset = models.ForeignKey(AccAsset, on_delete=models.CASCADE, related_name="movements")
    movement_type = models.CharField(max_length=16, choices=MOVEMENT_TYPE_CHOICES)
    date = models.DateField()
    amount_mga = models.DecimalField(max_digits=18, decimal_places=4)
    # Uniquement significatifs pour `movement_type="transfer"` (virement
    # d'un compte de classe 2 a un autre, ex. immobilisation en cours ->
    # immobilisation definitive) — nuls pour acquisition/cession.
    from_account = models.ForeignKey(
        AccAccount, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    to_account = models.ForeignKey(
        AccAccount, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # Reste null en V1 pour l'acquisition (cf. docstring
    # `services/assets.py::register_asset` — l'ecriture d'acquisition est
    # normalement deja passee par le flux d'achat/paiement qui n'existe pas
    # encore, `purchase`). Peut etre rattache a une ecriture reelle pour un
    # virement de poste ou une cession traites via ce service.
    move = models.ForeignKey(
        AccMove, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "acc_asset_movement"
        indexes = [models.Index(fields=["asset", "date"])]

    def __str__(self) -> str:
        return f"{self.asset} — {self.movement_type} ({self.date})"


class AccAssetDepreciation(BaseModel):
    """Une annuite d'amortissement calculee pour `asset`/`fiscal_year` —
    source de l'annexe "Etat des amortissements" (§1.11 du document annexe),
    cf. `services/assets.py::compute_annual_depreciation`."""

    asset = models.ForeignKey(
        AccAsset, on_delete=models.CASCADE, related_name="depreciation_entries"
    )
    fiscal_year = models.ForeignKey(AccFiscalYear, on_delete=models.PROTECT, related_name="+")
    opening_accumulated_mga = models.DecimalField(max_digits=18, decimal_places=4)
    annual_dotation_mga = models.DecimalField(max_digits=18, decimal_places=4)
    closing_accumulated_mga = models.DecimalField(max_digits=18, decimal_places=4)
    # Reste null si l'annuite n'a pas ete "postee" au grand livre
    # (`post=False`, par defaut — cf. docstring du service).
    move = models.ForeignKey(
        AccMove, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "acc_asset_depreciation"

    def __str__(self) -> str:
        return f"{self.asset} — {self.fiscal_year} : {self.annual_dotation_mga}"


class AccProvision(BaseModel, ReferenceMixin):
    """Une provision (§1.11 du document annexe, annexe "Etat des
    provisions") : dotation/reprise par exercice, `nature` en texte libre
    (le document ne propose pas de nomenclature fermee, contrairement aux
    categories d'immobilisation)."""

    nature = models.CharField(max_length=200)
    account = models.ForeignKey(AccAccount, on_delete=models.PROTECT, related_name="+")
    fiscal_year = models.ForeignKey(AccFiscalYear, on_delete=models.PROTECT, related_name="+")
    opening_amount_mga = models.DecimalField(max_digits=18, decimal_places=4)
    dotation_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    reprise_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    closing_amount_mga = models.DecimalField(max_digits=18, decimal_places=4)
    # Reste null en V1 : la comptabilisation reelle de la dotation/reprise
    # est une operation de cloture ordinaire, deja faisable manuellement via
    # `create_draft_move`/`add_line`/`post_move` (cf. docstring de
    # `services/assets.py::record_provision_movement`).
    move = models.ForeignKey(
        AccMove, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "acc_provision"

    def __str__(self) -> str:
        return self.reference or f"{self.nature} ({self.fiscal_year})"


class AccDcomDeclaration(BaseModel, ReferenceMixin):
    """ACC-DCOM1 (§1.8 du document annexe) : declaration du droit de
    communication (DCOM) — PAS un impot, une obligation declarative de
    recoupement (Art. 20.06.12 al. 3 et 20.06.15 al. 4 du CGI), due par
    toute entite dont le CA > 100 M Ar, agregeant les transactions
    commerciales PAR TIERS et par "nature de transaction" en 9 canevas
    normalises DGI.

    Reserve OECFM/DGI (§0.5, §3.5 du document annexe) : le document source
    NOMME les "9 canevas normalises de transactions par tiers (classification
    des rubriques : achats immobilises, etc.)" sans les enumerer
    integralement — ce n'est pas une omission de cette implementation mais
    une limite du document source lui-meme. `AccDcomLine.classification`
    utilise donc un classement de repli, deja modelisable depuis l'existant :
    la classe PCG (`AccAccount.account_class`, 1 a 7) du compte de
    contrepartie de chaque ligne d'ecriture, PAR tiers. C'est un
    classement RAISONNABLE mais PROVISOIRE, pas les 9 canevas DGI exacts —
    a confirmer/reconcilier avec un expert-comptable OECFM ou la DGI avant
    tout usage en production reelle (depot effectif sur
    entreprises.impots.mg/dconline)."""

    fiscal_year = models.ForeignKey(AccFiscalYear, on_delete=models.PROTECT, related_name="+")
    date_generated = models.DateField(auto_now_add=True)
    total_amount_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)

    class Meta:
        db_table = "acc_dcom_declaration"

    def __str__(self) -> str:
        return self.reference or f"DCOM {self.fiscal_year} ({self.id})"


class AccDcomLine(BaseModel):
    """Une ligne agregee (tiers, classification) de `AccDcomDeclaration` —
    cf. reserve de classification sur le modele parent. `partner_id` :
    jamais de FK Django vers `apps.partners.models.Partner` (regle de
    couplage n°1) — le nom d'affichage du tiers n'est resolu qu'a
    l'affichage du rapport (`services/reports.py::dcom_report`), via
    `apps.partners.services.public.get_partner_display_name`, jamais stocke
    ici."""

    declaration = models.ForeignKey(
        AccDcomDeclaration, on_delete=models.CASCADE, related_name="lines"
    )
    partner_id = models.UUIDField()
    classification = models.CharField(max_length=32)
    amount_mga = models.DecimalField(max_digits=18, decimal_places=4)

    class Meta:
        db_table = "acc_dcom_line"
        indexes = [models.Index(fields=["declaration", "partner_id"])]

    def __str__(self) -> str:
        return f"{self.partner_id} — {self.classification} : {self.amount_mga}"


class AccIrcmDeclaration(BaseModel, ReferenceMixin):
    """ACC-IRCM (§1.7 du document annexe) : declaration annuelle de l'Impot
    sur les Revenus des Capitaux Mobiliers — 20% sur les interets/revenus et
    produits des obligations et emprunts (assiette = comptes de produits
    financiers, classe 76-77 du PCG 2005), due par les entreprises au regime
    reel (IR), echeance le 15 mai N+1.

    `rate_pct` : champ (et non constante Python) pour permettre une
    correction ulterieure sans deploiement de code si la DGI revoit ce taux
    — defaut 20% (§1.7 du document annexe). Reserve OECFM/DGI (§0.5,
    §3.5) : ce taux, comme les autres parametres fiscaux de ce module, est
    repris d'un document non primaire, a confirmer avant tout usage en
    production reelle. Ideal cible (hors V1, cf. docstring de
    `services/ircm.py`) : source ce taux depuis
    `apps.core.services.regulatory.get_parameter`/`RegulatoryParameter`
    plutot que ce defaut de champ, une fois ce module lui-meme dote d'un
    jeu de parametres fiscaux malgaches verifies."""

    STATE_DRAFT = "draft"
    STATE_FILED = "filed"
    STATE_CHOICES = [
        (STATE_DRAFT, "Brouillon"),
        (STATE_FILED, "Deposee"),
    ]

    fiscal_year = models.ForeignKey(AccFiscalYear, on_delete=models.PROTECT, related_name="+")
    taxable_base_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    rate_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("20"))
    amount_due_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_DRAFT)

    class Meta:
        db_table = "acc_ircm_declaration"

    def __str__(self) -> str:
        return self.reference or f"IRCM {self.fiscal_year} ({self.id})"


class AccLocalTax(BaseModel, ReferenceMixin):
    """ACC-FONCIER (§1.9 du document annexe) : impots locaux fonciers geres
    au niveau communal (Madagascar n'a pas de "patente"/taxe professionnelle
    au sens marocain/francais/OHADA, contrairement a une hypothese initiale
    a verifier selon le document source) — IFT (Impot Foncier sur les
    Terrains, 1% de la valeur marchande du terrain nu) et IFPB (Impot
    Foncier sur la Propriete Batie, 5 a 10% de la valeur locative de
    l'immeuble, 1/3 de cette valeur pour le residentiel).

    Priorite BASSE (V2 au CDC) : pertinent seulement si le tenant est
    proprietaire de ses locaux/ateliers/entrepots — pas de generation
    automatique depuis le grand livre (donnee de propriete fonciere, pas
    une ecriture comptable), simple enregistrement manuel via
    `services/local_tax.py::record_local_tax`.

    `rate_pct` : pas de defaut "intelligent" pour l'IFPB — la fourchette
    5-10% (ou 1/3 de la valeur locative pour le residentiel) exige un taux
    par commune/type de propriete que seul le tenant connait ; seul l'IFT
    a un taux fixe (1%) au sens du document. Reserve OECFM/DGI (§0.5, §3.5
    du document annexe) : ces taux sont repris d'un document non primaire,
    a confirmer aupres de la commune/DGI competente avant tout usage en
    production reelle."""

    TAX_TYPE_IFT = "ift"
    TAX_TYPE_IFPB = "ifpb"
    TAX_TYPE_CHOICES = [
        (TAX_TYPE_IFT, "IFT — Impot foncier sur les terrains"),
        (TAX_TYPE_IFPB, "IFPB — Impot foncier sur la propriete batie"),
    ]

    STATE_DRAFT = "draft"
    STATE_FILED = "filed"
    STATE_CHOICES = [
        (STATE_DRAFT, "Brouillon"),
        (STATE_FILED, "Deposee"),
    ]

    tax_type = models.CharField(max_length=16, choices=TAX_TYPE_CHOICES)
    property_label = models.CharField(max_length=200)
    assessed_value_mga = models.DecimalField(max_digits=18, decimal_places=4)
    rate_pct = models.DecimalField(max_digits=5, decimal_places=2)
    fiscal_year = models.ForeignKey(AccFiscalYear, on_delete=models.PROTECT, related_name="+")
    amount_due_mga = models.DecimalField(max_digits=18, decimal_places=4)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_DRAFT)

    class Meta:
        db_table = "acc_local_tax"

    def __str__(self) -> str:
        return self.reference or f"{self.get_tax_type_display()} — {self.property_label}"


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
