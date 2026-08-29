"""Module `feasibility` (chantier FEA1-3, cf. plan) — permet de simuler la
faisabilite d'un produit ou d'un ensemble de produits (cout, prix, marge,
chaine complete de la conception a la vente/distribution) SANS qu'il
existe de client/prospect reel, pour evaluer le potentiel d'une idee.

**Decision de conception centrale** (`FeaStudyLine.variant_id`/
`hypothetical_spec`) : une ligne d'etude porte SOIT une variante catalogue
REELLE deja saisie (`variant_id`, UUID nullable — jamais de FK Django vers
`catalog.ProductVariant`, regle de couplage n1), SOIT une simple
description libre d'une hypothese qui n'existe encore nulle part ailleurs
dans le systeme (`hypothetical_spec`, JSONField : nom envisage, matiere,
notes...). Les deux champs sont mutuellement complementaires : une etude
100% exploratoire n'a AUCUNE variante reelle, une etude qui "chiffre un
produit deja au catalogue" peut se passer de `hypothetical_spec`. Aucune
contrainte `CheckConstraint` "l'un ou l'autre mais pas les deux" n'est
imposee : rien n'empeche de documenter les deux (ex. une variante reelle
existe deja mais l'etude porte sur une evolution de ses caracteristiques),
simplification assumee et disclosed plutot qu'une regle rigide sans besoin
metier explicite pour l'interdire.

`FeaStudyLine.computed_margin_pct` n'est JAMAIS saisi directement par
l'utilisateur — meme discipline que `StgObjective.status`
(`apps.strategy.models`) : un champ calcule, recalcule uniquement par
`services/simulation.py::simulate_study_line` (jamais mute a la main via
l'API/l'ecran)."""

from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models.base import BaseModel, ReferenceMixin

# Memes codes/libelles que `apps.strategy.models.SECTOR_CHOICES` (aligne
# volontairement, cf. cadrage du chantier) — pas d'import cross-app (regle
# de couplage n1, `feasibility` ne declare pas `strategy` en dependance) :
# une simple duplication de constantes, pas de logique partagee.
SECTOR_TEXTILE = "textile"
SECTOR_LEATHER = "cuir"
SECTOR_AGRIFOOD = "agroalimentaire"
SECTOR_IMPORT_EXPORT = "import_export"
SECTOR_CRAFT = "artisanat"
SECTOR_CHOICES = [
    (SECTOR_TEXTILE, _("Textile")),
    (SECTOR_LEATHER, _("Cuir et maroquinerie")),
    (SECTOR_AGRIFOOD, _("Agroalimentaire")),
    (SECTOR_IMPORT_EXPORT, _("Import-export generaliste")),
    (SECTOR_CRAFT, _("Artisanat")),
]


class FeaStudy(BaseModel, ReferenceMixin):
    """Etude de faisabilite (document numerote, cf. `ReferenceMixin` —
    meme patron que `SalesQuotation`/`FinLoanApplication`). Rattachee a un
    `owner` (`core.User`, l'auteur/porteur de l'etude) mais PAS a un
    partenaire/prospect (`partners`/`crm` ne sont pas des dependances de ce
    module, cf. `module.py` — c'est precisement le point de ce chantier :
    evaluer le potentiel d'une idee AVANT qu'un client reel existe)."""

    STATUS_DRAFT = "draft"
    STATUS_COMPLETED = "completed"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = [
        (STATUS_DRAFT, _("Brouillon")),
        (STATUS_COMPLETED, _("Terminee")),
        (STATUS_ARCHIVED, _("Archivee")),
    ]

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    sector_code = models.CharField(max_length=32, choices=SECTOR_CHOICES, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    owner = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "fea_study"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name

    def total_cost_mga(self) -> Decimal:
        return sum((line.total_cost_mga() for line in self.lines.all()), Decimal(0))

    def total_revenue_mga(self) -> Decimal:
        return sum((line.total_revenue_mga() for line in self.lines.all()), Decimal(0))


class FeaStudyLine(BaseModel):
    """Une ligne = un produit (reel ou hypothetique) chiffre pour l'etude.
    `assumed_qty` : quantite hypothetique retenue pour la simulation
    (jamais une commande reelle — c'est une hypothese de volume, cf.
    docstring module). `cost_breakdown` : resultat du calcul de
    `services/simulation.py` (`{"material": ..., "labor": ..., "overhead":
    ..., "total": ...}`, memes cles que `mrp.services.public.
    simulate_bom_cost`/`compute_planned_cost` — valeurs serialisees en
    `str` pour rester JSON-safe, jamais des `float`, cf. convention
    Decimal du projet) — rempli automatiquement si une BOM reelle existe
    pour la variante, sinon saisi/edite manuellement par l'utilisateur AVANT
    simulation (une etude 100% exploratoire n'a pas de BOM a chiffrer
    automatiquement)."""

    study = models.ForeignKey(FeaStudy, on_delete=models.CASCADE, related_name="lines")
    # Jamais de FK Django vers `apps.catalog.models.ProductVariant` (regle
    # de couplage n1) — resolu via `catalog.services.public` si renseigne.
    variant_id = models.UUIDField(null=True, blank=True)
    # Description libre de l'hypothese quand aucune variante reelle
    # n'existe encore (nom envisage, matiere, notes...) — cf. docstring
    # module pour la relation avec `variant_id`.
    hypothetical_spec = models.JSONField(default=dict, blank=True)
    assumed_qty = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal(1))
    assumed_unit_price_mga = models.DecimalField(
        max_digits=18, decimal_places=4, default=Decimal(0)
    )
    cost_breakdown = models.JSONField(default=dict, blank=True)
    # JAMAIS saisi directement par l'utilisateur — recalcule uniquement par
    # `services/simulation.py::simulate_study_line` (cf. docstring module).
    computed_margin_pct = models.DecimalField(max_digits=7, decimal_places=2, default=Decimal(0))

    class Meta:
        db_table = "fea_study_line"
        ordering = ["created_at"]

    def __str__(self) -> str:
        label = self.hypothetical_spec.get("name") if self.hypothetical_spec else None
        return label or str(self.variant_id) or str(self.id)

    def _cost_component(self, key: str) -> Decimal:
        raw = self.cost_breakdown.get(key)
        return Decimal(str(raw)) if raw is not None else Decimal(0)

    def total_cost_mga(self) -> Decimal:
        """Cout total de la ligne = cout unitaire total (`cost_breakdown
        ["total"]`, deja calcule pour `assumed_qty`, cf.
        `services/simulation.py`) — jamais remultiplie par `assumed_qty`
        ici, ce serait une double application de la quantite."""
        return self._cost_component("total")

    def total_revenue_mga(self) -> Decimal:
        return self.assumed_qty * self.assumed_unit_price_mga
