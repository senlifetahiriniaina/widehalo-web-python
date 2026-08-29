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
