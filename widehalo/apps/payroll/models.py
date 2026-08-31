"""Modeles du module `payroll` (§5.10 du CDC). Budget releve a 220 modeles
(PAY0) precisement pour accueillir les 11 entites nommement listees par le
CDC (§5.10.4) SANS fusion artificielle — a la difference de `presence`
(chantier precedent, budget alors serre a 180/180).

Couplage inter-app strict (regle n1) : `employee_id`/`department_id`/
`workshop_id`/`work_calendar_id` sont des UUID simples vers `presence`
(jamais de FK Django) ; `account_debit_id`/`account_credit_id`/`move_id`
sont des UUID simples vers `accounting`. `signed_document`/le PDF chiffre
d'un bulletin passent par `core.Document` polymorphe (content_type/
object_id), jamais un champ fichier dedie.

RG-PAY-10 (irreversibilite d'une periode VALIDEE) : une correction est un
bulletin RECTIFICATIF (`PayPayslip.rectifies`), jamais une modification en
place — meme discipline que l'immuabilite `AccMove` (Lot 2 A2)."""

from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _
from django_fsm import FSMField, transition

from apps.core.db.fields import EncryptedDecimalField
from apps.core.models.base import BaseModel, ReferenceMixin


class PayContractType(BaseModel):
    CATEGORY_CDI = "cdi"
    CATEGORY_CDD = "cdd"
    CATEGORY_TRIAL = "essai"
    CATEGORY_INTERNSHIP = "stage"
    CATEGORY_APPRENTICESHIP = "apprentissage"
    CATEGORY_DAILY = "journalier"
    CATEGORY_SEASONAL = "saisonnier"
    CATEGORY_SERVICE = "prestation"
    CATEGORY_CHOICES = [
        (CATEGORY_CDI, _("CDI")),
        (CATEGORY_CDD, _("CDD")),
        (CATEGORY_TRIAL, _("Essai")),
        (CATEGORY_INTERNSHIP, _("Stage")),
        (CATEGORY_APPRENTICESHIP, _("Apprentissage")),
        (CATEGORY_DAILY, _("Journalier")),
        (CATEGORY_SEASONAL, _("Saisonnier")),
        (CATEGORY_SERVICE, _("Prestation")),
    ]

    code = models.CharField(max_length=32)
    name = models.CharField(max_length=150)
    category = models.CharField(max_length=16, choices=CATEGORY_CHOICES)
    default_notice_days = models.PositiveSmallIntegerField(default=0)
    max_duration_months = models.PositiveSmallIntegerField(null=True, blank=True)
    is_renewable = models.BooleanField(default=False)

    class Meta:
        db_table = "pay_contract_type"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_pay_contract_type_code")
        ]

    def __str__(self) -> str:
        return self.name


class PaySalaryStructure(BaseModel):
    """Structure salariale = liste ORDONNEE de `PaySalaryRule` (moteur
    §5.10.5). `parent` permet un heritage de structures (ex. une structure
    "Ouvrier atelier" qui herite d'une structure "Base MG")."""

    code = models.CharField(max_length=32)
    name = models.CharField(max_length=150)
    country = models.CharField(max_length=2, default="MG")
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "pay_salary_structure"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_pay_structure_code")
        ]

    def __str__(self) -> str:
        return self.name


class PaySalaryRule(BaseModel):
    """Une regle sequencee d'une structure salariale — PAY-M1..M5."""

    CATEGORY_BASE = "base"
    CATEGORY_GROSS = "brut"
    CATEGORY_EMPLOYEE_CONTRIBUTION = "cotisation_salariale"
    CATEGORY_EMPLOYER_CONTRIBUTION = "cotisation_patronale"
    CATEGORY_TAX = "impot"
    CATEGORY_DEDUCTION = "retenue"
    CATEGORY_TAXABLE_NET = "net_imposable"
    CATEGORY_NET_TO_PAY = "net_a_payer"
    CATEGORY_CHOICES = [
        (CATEGORY_BASE, _("Base")),
        (CATEGORY_GROSS, _("Brut")),
        (CATEGORY_EMPLOYEE_CONTRIBUTION, _("Cotisation salariale")),
        (CATEGORY_EMPLOYER_CONTRIBUTION, _("Cotisation patronale")),
        (CATEGORY_TAX, _("Impôt")),
        (CATEGORY_DEDUCTION, _("Retenue")),
        (CATEGORY_TAXABLE_NET, _("Net imposable")),
        (CATEGORY_NET_TO_PAY, _("Net a payer")),
    ]

    CONDITION_ALWAYS = "toujours"
    CONDITION_PYTHON = "python"
    CONDITION_RANGE = "plage"
    CONDITION_CHOICES = [
        (CONDITION_ALWAYS, _("Toujours")),
        (CONDITION_PYTHON, _("Expression")),
        (CONDITION_RANGE, _("Plage")),
    ]

    AMOUNT_FIXED = "fixe"
    AMOUNT_PERCENT = "pourcentage"
    AMOUNT_PYTHON = "python"
    AMOUNT_TYPE_CHOICES = [
        (AMOUNT_FIXED, _("Fixe")),
        (AMOUNT_PERCENT, _("Pourcentage")),
        (AMOUNT_PYTHON, _("Expression")),
    ]

    structure = models.ForeignKey(
        PaySalaryStructure, on_delete=models.CASCADE, related_name="rules"
    )
    sequence = models.PositiveIntegerField(default=10)
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=150)
    category = models.CharField(max_length=24, choices=CATEGORY_CHOICES)
    condition_type = models.CharField(
        max_length=16, choices=CONDITION_CHOICES, default=CONDITION_ALWAYS
    )
    # PAY-M1 : expression evaluee par `apps.payroll.services.expr.safe_eval`
    # UNIQUEMENT, jamais `eval()` natif. Pour `condition_type="plage"` :
    # `{"base_code": "BRUT", "min": 0, "max": 350000}` (JSON, pas de texte
    # libre) — pas une expression a evaluer, une simple comparaison bornee.
    condition = models.TextField(blank=True)
    amount_type = models.CharField(max_length=16, choices=AMOUNT_TYPE_CHOICES, default=AMOUNT_FIXED)
    # Fixe : montant Decimal (JSON number/string). Pourcentage : taux
    # (JSON number, applique a `base_code`). Expression : texte de
    # l'expression PAY-M1.
    amount = models.TextField(blank=True)
    base_code = models.CharField(max_length=32, blank=True)
    appears_on_payslip = models.BooleanField(default=True)
    # UUID simple vers `accounting.AccAccount` (couplage n1) — resolu par
    # `services.accounting_gap` UNIQUEMENT au moment de comptabiliser
    # (RG-PAY-8), jamais avant.
    account_debit_id = models.UUIDField(null=True, blank=True)
    account_credit_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "pay_salary_rule"
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(fields=["structure", "code"], name="uniq_pay_salary_rule_code")
        ]

    def __str__(self) -> str:
        return f"{self.sequence:03d} {self.code} — {self.name}"


class PayContract(BaseModel, ReferenceMixin):
    """`reference` (ReferenceMixin, sequence PAYC-<annee>-NNNN). RG-PAY-6 :
    `parent_contract` chaine les avenants (contrat ENFANT), historique
    conserve — jamais de modification en place d'un contrat clos."""

    STATE_DRAFT = "draft"
    STATE_ACTIVE = "active"
    STATE_SUSPENDED = "suspended"
    STATE_ENDED = "ended"
    STATE_CHOICES = [
        (STATE_DRAFT, _("Brouillon")),
        (STATE_ACTIVE, _("Actif")),
        (STATE_SUSPENDED, _("Suspendu")),
        (STATE_ENDED, _("Termine")),
    ]

    WAGE_MONTHLY = "mensuel"
    WAGE_HOURLY = "horaire"
    WAGE_DAILY = "journalier"
    WAGE_PIECE = "piece"
    WAGE_TYPE_CHOICES = [
        (WAGE_MONTHLY, _("Mensuel")),
        (WAGE_HOURLY, _("Horaire")),
        (WAGE_DAILY, _("Journalier")),
        (WAGE_PIECE, _("Aux pièces")),
    ]

    # Couplage n1 : UUID simple vers `presence.PrsEmployee` (jamais de FK).
    employee_id = models.UUIDField()
    type = models.ForeignKey(PayContractType, on_delete=models.PROTECT, related_name="contracts")
    date_start = models.DateField()
    date_end = models.DateField(null=True, blank=True)
    trial_end = models.DateField(null=True, blank=True)
    job_title = models.CharField(max_length=150, blank=True)
    # UUID simples vers `presence.PrsDepartment`/`mrp.MrpWorkshop` —
    # jamais de FK (couplage n1).
    department_id = models.UUIDField(null=True, blank=True)
    workshop_id = models.UUIDField(null=True, blank=True)
    wage_base = models.DecimalField(max_digits=18, decimal_places=4)
    wage_type = models.CharField(max_length=16, choices=WAGE_TYPE_CHOICES, default=WAGE_MONTHLY)
    work_calendar_id = models.UUIDField(null=True, blank=True)
    salary_structure = models.ForeignKey(
        PaySalaryStructure, on_delete=models.PROTECT, related_name="contracts"
    )
    state = FSMField(default=STATE_DRAFT, choices=STATE_CHOICES)
    # `core.Document` polymorphe (content_type/object_id sur cette
    # instance) porte le contrat signe — pas de champ fichier dedie ici.
    notice_days = models.PositiveSmallIntegerField(default=0)
    parent_contract = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="amendments"
    )

    class Meta:
        db_table = "pay_contract"

    def __str__(self) -> str:
        return self.reference or f"Contrat {self.employee_id} {self.date_start}"

    @transition(field=state, source=STATE_DRAFT, target=STATE_ACTIVE)
    def activate(self) -> None:
        pass

    @transition(field=state, source=STATE_ACTIVE, target=STATE_SUSPENDED)
    def suspend(self) -> None:
        pass

    @transition(field=state, source=STATE_SUSPENDED, target=STATE_ACTIVE)
    def resume(self) -> None:
        pass

    @transition(field=state, source=[STATE_ACTIVE, STATE_SUSPENDED], target=STATE_ENDED)
    def end(self) -> None:
        pass


class PayContractBenefit(BaseModel):
    TYPE_TRANSPORT = "prime_transport"
    TYPE_SENIORITY = "prime_anciennete"
    TYPE_PERFORMANCE = "prime_rendement"
    TYPE_HOUSING = "indemnite_logement"
    TYPE_MEAL = "indemnite_repas"
    TYPE_PHONE = "telephone"
    TYPE_HEALTH_INSURANCE = "assurance_sante"
    TYPE_BENEFIT_IN_KIND = "avantage_nature"
    TYPE_CHOICES = [
        (TYPE_TRANSPORT, _("Prime de transport")),
        (TYPE_SENIORITY, _("Prime d'ancienneté")),
        (TYPE_PERFORMANCE, _("Prime de rendement")),
        (TYPE_HOUSING, _("Indemnité de logement")),
        (TYPE_MEAL, _("Indemnité de repas")),
        (TYPE_PHONE, _("Téléphone")),
        (TYPE_HEALTH_INSURANCE, _("Assurance santé")),
        (TYPE_BENEFIT_IN_KIND, _("Avantage en nature")),
    ]

    COMPUTATION_FIXED = "fixe"
    COMPUTATION_PERCENT = "pourcentage"
    COMPUTATION_FORMULA = "formule"
    COMPUTATION_CHOICES = [
        (COMPUTATION_FIXED, _("Fixe")),
        (COMPUTATION_PERCENT, _("Pourcentage")),
        (COMPUTATION_FORMULA, _("Formule")),
    ]

    FREQUENCY_MONTHLY = "mensuelle"
    FREQUENCY_YEARLY = "annuelle"
    FREQUENCY_ONE_TIME = "ponctuelle"
    FREQUENCY_CHOICES = [
        (FREQUENCY_MONTHLY, _("Mensuelle")),
        (FREQUENCY_YEARLY, _("Annuelle")),
        (FREQUENCY_ONE_TIME, _("Ponctuelle")),
    ]

    contract = models.ForeignKey(PayContract, on_delete=models.CASCADE, related_name="benefits")
    type = models.CharField(max_length=24, choices=TYPE_CHOICES)
    amount = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal(0))
    computation = models.CharField(
        max_length=16, choices=COMPUTATION_CHOICES, default=COMPUTATION_FIXED
    )
    is_taxable = models.BooleanField(default=True)
    is_subject_to_social = models.BooleanField(default=True)
    frequency = models.CharField(
        max_length=16, choices=FREQUENCY_CHOICES, default=FREQUENCY_MONTHLY
    )
    date_from = models.DateField(null=True, blank=True)
    date_to = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "pay_contract_benefit"

    def __str__(self) -> str:
        return f"{self.contract} — {self.type}"


class PayPeriod(BaseModel):
    """Workflow §5.10.7 (attempt_transition + .save(update_fields=...)
    obligatoire chez tout appelant, garde-fou AST existant)."""

    STATE_OPEN = "ouverte"
    STATE_COMPUTING = "en_calcul"
    STATE_VERIFIED = "verifiee"
    STATE_VALIDATED = "validee"
    STATE_PAID = "payee"
    STATE_CLOSED = "cloturee"
    STATE_CHOICES = [
        (STATE_OPEN, _("Ouverte")),
        (STATE_COMPUTING, _("En calcul")),
        (STATE_VERIFIED, _("Vérifiée")),
        (STATE_VALIDATED, _("Validée")),
        (STATE_PAID, _("Payée")),
        (STATE_CLOSED, _("Clôturée")),
    ]

    code = models.CharField(max_length=32)
    date_from = models.DateField()
    date_to = models.DateField()
    payment_date = models.DateField()
    state = FSMField(default=STATE_OPEN, choices=STATE_CHOICES)

    class Meta:
        db_table = "pay_period"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_pay_period_code")
        ]

    def __str__(self) -> str:
        return self.code

    @transition(field=state, source=[STATE_OPEN, STATE_VERIFIED], target=STATE_COMPUTING)
    def start_compute(self) -> None:
        pass

    @transition(field=state, source=STATE_COMPUTING, target=STATE_VERIFIED)
    def verify(self) -> None:
        pass

    @transition(field=state, source=STATE_VERIFIED, target=STATE_VALIDATED)
    def validate(self) -> None:
        pass

    @transition(field=state, source=STATE_VALIDATED, target=STATE_PAID)
    def mark_paid(self) -> None:
        pass

    @transition(field=state, source=STATE_PAID, target=STATE_CLOSED)
    def close(self) -> None:
        pass


class PayPayslip(BaseModel, ReferenceMixin):
    """RG-PAY-10 : une fois `period.state="validee"`, plus aucune
    modification en place — une correction cree un NOUVEAU bulletin
    `rectifies=<original>`, jamais un `save()` sur l'original."""

    STATE_DRAFT = "draft"
    STATE_COMPUTED = "computed"
    STATE_TO_APPROVE = "to_approve"
    STATE_APPROVED = "approved"
    STATE_PAID = "paid"
    STATE_CANCELLED = "cancelled"
    STATE_CHOICES = [
        (STATE_DRAFT, _("Brouillon")),
        (STATE_COMPUTED, _("Calcule")),
        (STATE_TO_APPROVE, _("A approuver")),
        (STATE_APPROVED, _("Approuve")),
        (STATE_PAID, _("Paye")),
        (STATE_CANCELLED, _("Annule")),
    ]

    PAYMENT_BANK = "banque"
    PAYMENT_MOBILE_MONEY = "mobile_money"
    PAYMENT_CASH = "especes"
    PAYMENT_CHOICES = [
        (PAYMENT_BANK, _("Virement bancaire")),
        (PAYMENT_MOBILE_MONEY, _("Mobile money")),
        (PAYMENT_CASH, _("Espèces")),
    ]

    employee_id = models.UUIDField()
    contract = models.ForeignKey(PayContract, on_delete=models.PROTECT, related_name="payslips")
    period = models.ForeignKey(PayPeriod, on_delete=models.PROTECT, related_name="payslips")
    batch = models.ForeignKey(
        "PayBatch", null=True, blank=True, on_delete=models.SET_NULL, related_name="payslips"
    )
    date_from = models.DateField()
    date_to = models.DateField()
    worked_days = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal(0))
    worked_hours = models.DecimalField(max_digits=7, decimal_places=2, default=Decimal(0))
    # [{"category": str, "days": "12.00", "pay_rate_pct": "100.00"}, ...]
    absence_days = models.JSONField(default=list, blank=True)
    # {"h_sup_30": "5.00", "h_sup_50": "2.00", ...}
    overtime_hours = models.JSONField(default=dict, blank=True)
    state = FSMField(default=STATE_DRAFT, choices=STATE_CHOICES)
    gross = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal(0))
    taxable_base = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal(0))
    irsa = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal(0))
    social_employee = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal(0))
    social_employer = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal(0))
    # Chiffre (RG-PAY-9/enrichissement chiffrement) : montant final
    # individuellement sensible, en plus du controle applicatif d'acces.
    net_to_pay = EncryptedDecimalField(max_digits=18, decimal_places=4, default=Decimal(0))
    payment_method = models.CharField(max_length=16, choices=PAYMENT_CHOICES, default=PAYMENT_BANK)
    payment_reference = models.CharField(max_length=100, blank=True)
    # UUID simple vers `accounting.AccMove` (couplage n1, RG-PAY-8).
    move_id = models.UUIDField(null=True, blank=True)
    rectifies = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="rectifications"
    )

    class Meta:
        db_table = "pay_payslip"

    def __str__(self) -> str:
        return self.reference or f"Bulletin {self.employee_id} {self.period_id}"

    @transition(field=state, source=[STATE_DRAFT, STATE_COMPUTED], target=STATE_COMPUTED)
    def mark_computed(self) -> None:
        pass

    @transition(field=state, source=STATE_COMPUTED, target=STATE_TO_APPROVE)
    def submit_for_approval(self) -> None:
        pass

    @transition(field=state, source=STATE_TO_APPROVE, target=STATE_APPROVED)
    def approve(self) -> None:
        pass

    @transition(field=state, source=STATE_APPROVED, target=STATE_PAID)
    def mark_paid(self) -> None:
        pass

    @transition(
        field=state,
        source=[STATE_DRAFT, STATE_COMPUTED, STATE_TO_APPROVE],
        target=STATE_CANCELLED,
    )
    def cancel(self) -> None:
        pass


class PayPayslipLine(BaseModel):
    payslip = models.ForeignKey(PayPayslip, on_delete=models.CASCADE, related_name="lines")
    rule = models.ForeignKey(
        PaySalaryRule, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    sequence = models.PositiveIntegerField(default=10)
    code = models.CharField(max_length=32)
    label = models.CharField(max_length=255)
    category = models.CharField(max_length=24, choices=PaySalaryRule.CATEGORY_CHOICES)
    base = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal(0))
    rate = models.DecimalField(max_digits=9, decimal_places=4, null=True, blank=True)
    amount = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal(0))
    is_employer_charge = models.BooleanField(default=False)

    class Meta:
        db_table = "pay_payslip_line"
        ordering = ["sequence"]

    def __str__(self) -> str:
        return f"{self.payslip} — {self.code} {self.amount}"


class PayBatch(BaseModel, ReferenceMixin):
    STATE_DRAFT = "draft"
    STATE_CONTROLLED = "controlled"
    STATE_VALIDATED = "validated"
    STATE_CANCELLED = "cancelled"
    STATE_CHOICES = [
        (STATE_DRAFT, _("Brouillon")),
        (STATE_CONTROLLED, _("Controle")),
        (STATE_VALIDATED, _("Valide")),
        (STATE_CANCELLED, _("Annule")),
    ]

    period = models.ForeignKey(PayPeriod, on_delete=models.PROTECT, related_name="batches")
    state = FSMField(default=STATE_DRAFT, choices=STATE_CHOICES)
    total_gross = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal(0))
    total_net = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal(0))
    total_social = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal(0))
    validated_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "pay_batch"

    def __str__(self) -> str:
        return self.reference or f"Lot {self.period_id}"

    @transition(field=state, source=STATE_DRAFT, target=STATE_CONTROLLED)
    def control(self) -> None:
        pass

    @transition(field=state, source=STATE_CONTROLLED, target=STATE_VALIDATED)
    def validate(self) -> None:
        pass

    @transition(field=state, source=[STATE_DRAFT, STATE_CONTROLLED], target=STATE_CANCELLED)
    def cancel(self) -> None:
        pass


class PayDeclaration(BaseModel, ReferenceMixin):
    TYPE_IRSA = "irsa"
    TYPE_CNAPS = "cnaps"
    TYPE_OSTIE = "ostie"
    TYPE_DTS = "dts"
    TYPE_CHOICES = [
        (TYPE_IRSA, _("IRSA")),
        (TYPE_CNAPS, _("CNaPS")),
        (TYPE_OSTIE, _("OSTIE")),
        (TYPE_DTS, _("DTS")),
    ]

    STATE_DRAFT = "draft"
    STATE_SUBMITTED = "submitted"
    STATE_CHOICES = [
        (STATE_DRAFT, _("Brouillon")),
        (STATE_SUBMITTED, _("Soumise")),
    ]

    period = models.ForeignKey(PayPeriod, on_delete=models.PROTECT, related_name="declarations")
    type = models.CharField(max_length=8, choices=TYPE_CHOICES)
    state = FSMField(default=STATE_DRAFT, choices=STATE_CHOICES)
    amount = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal(0))
    # `core.Document` polymorphe porte le document genere/depose — pas de
    # champ fichier dedie ici.
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "pay_declaration"

    def __str__(self) -> str:
        return self.reference or f"{self.type} {self.period_id}"

    @transition(field=state, source=STATE_DRAFT, target=STATE_SUBMITTED)
    def submit(self) -> None:
        pass


class PayAdvance(BaseModel, ReferenceMixin):
    STATE_REQUESTED = "requested"
    STATE_APPROVED = "approved"
    STATE_REPAYING = "repaying"
    STATE_SETTLED = "settled"
    STATE_REJECTED = "rejected"
    STATE_CHOICES = [
        (STATE_REQUESTED, _("Demandée")),
        (STATE_APPROVED, _("Approuvée")),
        (STATE_REPAYING, _("En remboursement")),
        (STATE_SETTLED, _("Soldée")),
        (STATE_REJECTED, _("Refusée")),
    ]

    employee_id = models.UUIDField()
    date = models.DateField()
    amount = models.DecimalField(max_digits=18, decimal_places=4)
    reason = models.CharField(max_length=255, blank=True)
    repayment_months = models.PositiveSmallIntegerField(default=1)
    remaining = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal(0))
    state = FSMField(default=STATE_REQUESTED, choices=STATE_CHOICES)

    class Meta:
        db_table = "pay_advance"

    def __str__(self) -> str:
        return self.reference or f"Avance {self.employee_id} {self.date}"

    @transition(field=state, source=STATE_REQUESTED, target=STATE_APPROVED)
    def approve(self) -> None:
        pass

    @transition(field=state, source=STATE_REQUESTED, target=STATE_REJECTED)
    def reject(self) -> None:
        pass

    @transition(field=state, source=STATE_APPROVED, target=STATE_REPAYING)
    def start_repayment(self) -> None:
        pass

    @transition(field=state, source=STATE_REPAYING, target=STATE_SETTLED)
    def settle(self) -> None:
        pass
