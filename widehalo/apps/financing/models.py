"""Module `financing` (dossiers de financement bancaire PME) — cf. plan,
section « Nouveau sous-module `financing` », sous-sequencement FIN1-FIN4.

Sous-module deliberement differe jusqu'a ce que `sales`/`purchase`/
`logistics` existent (un CREDOC — credit documentaire a l'importation, FIN3
— est rattache a une commande fournisseur et une expedition, toutes deux
desormais reelles). Dependances declarees (`module.py`) : `core`,
`accounting`, `sales`, `purchase`, `logistics`, toutes via `services.public`
uniquement — jamais de FK Django cross-app (regle de couplage n1, comme
partout ailleurs dans ce depot).

**Simplification assumee et disclosed (`bank_partner`)** : le CDC/plan
mentionne un `bank_partner` mais `financing` NE declare PAS `partners`
comme dependance (absent de la liste ci-dessus, contrairement a
`purchase`/`sales` qui la declarent explicitement) — une banque
n'est donc PAS necessairement un `Partner` existant du module `partners`.
`bank_partner_id` reste un simple `UUIDField` optionnel (jamais resolu via
`partners.services.public`, qui n'est pas dans le perimetre de couplage
autorise de ce module) ; `bank_name` (texte libre) porte l'affichage —
a faire evoluer vers un vrai partenaire "banque" si/quand `partners`
introduit un role dedie et que `financing` declare la dependance."""

from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models.base import BaseModel, ReferenceMixin


class FinLoanApplication(BaseModel, ReferenceMixin):
    """Dossier de demande de financement bancaire (FIN1) — cycle de vie
    SIMPLE (`demande -> soumis -> decision`), volontairement PAS une FSM
    `django-fsm-2` complete : c'est un cycle de vie de DOSSIER administratif
    a trois etapes lineaires (jamais d'annulation/litige a modeliser),
    contrairement a `FinCredoc` (FIN3, workflow RUU 600 a 5 etats avec
    branchements reels) qui, lui, justifie la machine a etats complete.
    Meme discipline de simplification assumee que `PurRequisition`/
    `AccBudget` (transitions triviales, garde metier en service plutot
    qu'en FSM)."""

    STATE_DRAFT = "draft"
    STATE_SUBMITTED = "submitted"
    STATE_ACCEPTED = "accepted"
    STATE_REJECTED = "rejected"
    STATE_CHOICES = [
        (STATE_DRAFT, _("Demande (brouillon)")),
        (STATE_SUBMITTED, _("Soumis a la banque")),
        (STATE_ACCEPTED, _("Accepte")),
        (STATE_REJECTED, _("Rejete")),
    ]

    LOAN_TYPE_INVESTMENT_ST_MT = "investissement_ct_mt"
    LOAN_TYPE_INVESTMENT_LT = "investissement_lt"
    LOAN_TYPE_OPERATING = "fonctionnement"
    LOAN_TYPE_CREDOC = "credoc"
    LOAN_TYPE_CHOICES = [
        (LOAN_TYPE_INVESTMENT_ST_MT, _("Investissement court/moyen terme")),
        (LOAN_TYPE_INVESTMENT_LT, _("Investissement long terme")),
        (LOAN_TYPE_OPERATING, _("Fonctionnement")),
        (LOAN_TYPE_CREDOC, _("Credit documentaire (CREDOC)")),
    ]

    type = models.CharField(max_length=32, choices=LOAN_TYPE_CHOICES)  # noqa: A003
    # Jamais de FK Django vers `apps.partners.models.Partner` — cf.
    # docstring du module ci-dessus.
    bank_partner_id = models.UUIDField(null=True, blank=True)
    bank_name = models.CharField(max_length=255, blank=True)
    amount_requested_mga = models.DecimalField(max_digits=18, decimal_places=4)
    currency = models.CharField(max_length=3, default="MGA")
    duration_months = models.PositiveIntegerField()
    purpose = models.TextField(blank=True)
    # RG observee au cadrage (pas de reference chiffree unique dans le
    # document source pour cette valeur par defaut) : 30% d'apport propre
    # par defaut, modifiable au cas par cas.
    own_contribution_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal(30))
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_DRAFT)
    submission_date = models.DateField(null=True, blank=True)
    decision_date = models.DateField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    class Meta:
        db_table = "fin_loan_application"

    def __str__(self) -> str:
        return self.reference or str(self.id)


class FinFinancingPlanLine(BaseModel):
    """Repartition du plan de financement d'un dossier (fonds propres /
    emprunt sollicite / autre source) — FIN1. Pas de contrainte d'equilibre
    (somme des lignes == montant du projet) posee au niveau du modele :
    verifiee en service (`services/loan_applications.py::
    validate_financing_plan_balance`) pour rester une aide au diagnostic
    plutot qu'un blocage rigide (un dossier peut legitimement etre en cours
    de construction, lignes incompletes)."""

    SOURCE_OWN_FUNDS = "fonds_propres"
    SOURCE_LOAN_REQUESTED = "emprunt_sollicite"
    SOURCE_OTHER = "autre"
    SOURCE_CHOICES = [
        (SOURCE_OWN_FUNDS, _("Fonds propres")),
        (SOURCE_LOAN_REQUESTED, _("Emprunt sollicite")),
        (SOURCE_OTHER, _("Autre source")),
    ]

    loan_application = models.ForeignKey(
        FinLoanApplication, on_delete=models.CASCADE, related_name="financing_plan_lines"
    )
    source = models.CharField(max_length=32, choices=SOURCE_CHOICES)
    label = models.CharField(max_length=255, blank=True)
    amount_mga = models.DecimalField(max_digits=18, decimal_places=4)

    class Meta:
        db_table = "fin_financing_plan_line"

    def __str__(self) -> str:
        return f"{self.get_source_display()}: {self.amount_mga}"


class FinForecastScenario(BaseModel, ReferenceMixin):
    """Scenario de prevision (FIN2) rattache — optionnellement — a un
    dossier de financement : conteneur des lignes de compte de resultat/
    bilan/tresorerie previsionnels (`FinForecastScenarioLine`).

    **Simplification assumee et disclosed** : contrairement a l'intention
    initiale du plan (« alimente par `sales.services.public` pour les
    previsions de vente ET `mrp`/`payroll`/`accounting` pour les couts/
    projections »), le sous-sequencement final (cf. plan, section
    "Sous-sequencement") a restreint l'auto-alimentation reelle en LIGNES
    DE SCENARIO (montants MGA) a `payroll.services.public.
    get_payroll_mass_projection` (charges de personnel) et `accounting.
    services.public.get_treasury_forecast_summary` (tresorerie) — cf.
    `services/forecast.py::populate_income_statement_from_payroll_
    projection`/`populate_cash_flow_from_treasury_forecast`.
    `sales.services.public.get_forecast_summary` renvoie une prevision en
    UNITES (`qty_forecast`), jamais en MGA — `financing` NE DECLARE PAS
    `catalog` comme dependance (cf. `module.py`), necessaire pour valoriser
    ces unites en chiffre d'affaires previsionnel. Plutot que d'inventer un
    prix ou d'ajouter une dependance non prevue par le plan, la prevision
    de vente est affichee comme section INFORMATIVE (volumes, pas de
    montant) directement dans le rapport composite FIN-DOSSIER (FIN4,
    `services/reports.py`), jamais materialisee en `FinForecastScenarioLine`
    — a faire evoluer si/quand `financing` declare `catalog` comme
    dependance reelle. Les lignes de chiffre d'affaires previsionnel
    (produits) du compte de resultat restent donc, en v1, une SAISIE
    MANUELLE (`add_scenario_line`), comme toute ligne de ce scenario."""

    STATEMENT_INCOME = "income_statement"
    STATEMENT_BALANCE_SHEET = "balance_sheet"
    STATEMENT_CASH_FLOW = "cash_flow"
    STATEMENT_CHOICES = [
        (STATEMENT_INCOME, _("Compte de resultat previsionnel")),
        (STATEMENT_BALANCE_SHEET, _("Bilan previsionnel")),
        (STATEMENT_CASH_FLOW, _("Tresorerie previsionnelle")),
    ]

    loan_application = models.ForeignKey(
        FinLoanApplication,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="forecast_scenarios",
    )
    name = models.CharField(max_length=255)
    period_start = models.DateField()
    period_end = models.DateField()
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "fin_forecast_scenario"

    def __str__(self) -> str:
        return self.reference or self.name


class FinForecastScenarioLine(BaseModel):
    """Ligne d'un scenario de prevision — `statement_type` distingue les 3
    etats financiers previsionnels demandes par le plan (compte de
    resultat/bilan/tresorerie), tous portes par le MEME modele de ligne
    (memes 4 champs : libelle, periode, montant, source) plutot que 3
    modeles paralleles quasi-identiques — simplification assumee, meme
    esprit que `AccBudgetLine` (A14) qui ne distingue pas non plus les
    natures de charge/produit par un modele different.

    **Convention de signe** (documentee, jamais imposee par une contrainte
    BDD) : `amount_mga` positif = produit/entree/actif, negatif = charge/
    sortie/passif — coherent avec la convention deja en usage dans
    `accounting.services.public.create_customer_invoice_from_source`
    (lignes signees, jamais 2 colonnes debit/credit dans cet objet simple).

    `source` distingue une ligne saisie MANUELLEMENT (defaut) d'une ligne
    injectee automatiquement par un des 2 gaps `services.public` cites
    dans la docstring `FinForecastScenario` — jamais recalculee sur place,
    une regeneration re-appelle simplement la fonction de peuplement, qui
    supprime puis recree ses propres lignes marquees de la meme `source`
    (cf. `services/forecast.py`)."""

    SOURCE_MANUAL = "manuel"
    SOURCE_PAYROLL_PROJECTION = "payroll_projection"
    SOURCE_TREASURY_FORECAST = "treasury_forecast"
    SOURCE_CHOICES = [
        (SOURCE_MANUAL, _("Saisie manuelle")),
        (SOURCE_PAYROLL_PROJECTION, _("Projection masse salariale (payroll)")),
        (SOURCE_TREASURY_FORECAST, _("Tresorerie previsionnelle (accounting)")),
    ]

    scenario = models.ForeignKey(
        FinForecastScenario, on_delete=models.CASCADE, related_name="lines"
    )
    statement_type = models.CharField(max_length=32, choices=FinForecastScenario.STATEMENT_CHOICES)
    label = models.CharField(max_length=255)
    # Format "AAAA-MM", meme convention que `sales.SalesForecast.period`.
    period = models.CharField(max_length=7)
    amount_mga = models.DecimalField(max_digits=18, decimal_places=4)
    source = models.CharField(max_length=32, choices=SOURCE_CHOICES, default=SOURCE_MANUAL)

    class Meta:
        db_table = "fin_forecast_scenario_line"

    def __str__(self) -> str:
        return f"{self.label} ({self.period}): {self.amount_mga}"


class FinGuarantee(BaseModel, ReferenceMixin):
    """Surete rattachee a un dossier de financement (FIN2). La regle
    "valeur estimee >= 120% du credit" (observee au cadrage, cf. plan)
    n'est PAS une contrainte de modele/creation (une premiere surete peut
    legitimement etre insuffisante avant qu'une seconde ne soit ajoutee) :
    verifiee en service (`services/guarantees.py::check_guarantee_
    coverage`), meme discipline "aide au diagnostic, jamais un blocage
    rigide" que `validate_financing_plan_balance` (FIN1).

    Document juridique attache via `core.services.documents.store_document`
    (`content_object=guarantee`) — pas de FK dediee ici, le lien passe par
    `content_type`/`object_id` generiques deja portes par `core.Document`
    (regle de nommage generic FK n2 du projet)."""

    FORMALIZATION_PENDING = "a_formaliser"
    FORMALIZATION_IN_PROGRESS = "en_cours"
    FORMALIZATION_DONE = "formalisee"
    FORMALIZATION_CHOICES = [
        (FORMALIZATION_PENDING, _("A formaliser")),
        (FORMALIZATION_IN_PROGRESS, _("En cours de formalisation")),
        (FORMALIZATION_DONE, _("Formalisee")),
    ]

    GUARANTEE_TYPE_MORTGAGE = "hypotheque"
    GUARANTEE_TYPE_PLEDGE = "nantissement"
    GUARANTEE_TYPE_PERSONAL_SURETY = "caution_personnelle"
    GUARANTEE_TYPE_BANK_GUARANTEE = "caution_bancaire"
    GUARANTEE_TYPE_LIEN = "gage"
    GUARANTEE_TYPE_OTHER = "autre"
    GUARANTEE_TYPE_CHOICES = [
        (GUARANTEE_TYPE_MORTGAGE, _("Hypotheque")),
        (GUARANTEE_TYPE_PLEDGE, _("Nantissement")),
        (GUARANTEE_TYPE_PERSONAL_SURETY, _("Caution personnelle")),
        (GUARANTEE_TYPE_BANK_GUARANTEE, _("Caution bancaire")),
        (GUARANTEE_TYPE_LIEN, _("Gage")),
        (GUARANTEE_TYPE_OTHER, _("Autre surete")),
    ]

    loan_application = models.ForeignKey(
        FinLoanApplication, on_delete=models.CASCADE, related_name="guarantees"
    )
    type = models.CharField(max_length=32, choices=GUARANTEE_TYPE_CHOICES)  # noqa: A003
    asset_description = models.TextField(blank=True)
    estimated_value_mga = models.DecimalField(max_digits=18, decimal_places=4)
    formalization_status = models.CharField(
        max_length=16, choices=FORMALIZATION_CHOICES, default=FORMALIZATION_PENDING
    )

    class Meta:
        db_table = "fin_guarantee"

    def __str__(self) -> str:
        return self.reference or str(self.id)
