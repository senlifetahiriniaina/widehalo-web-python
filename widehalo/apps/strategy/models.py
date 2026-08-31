"""Module `strategy` (Strategie & Pilotage) — hors CDC, cadre directement
avec l'utilisateur (cf. plan, section dediee). Cascade OKR complete
(entreprise -> departement -> individuel) et referentiel de benchmarks
sectoriels (5 secteurs, seul le textile est peuple de valeurs reelles pour
l'instant).

**Simplification assumee et disclosed** (`StgObjective.status`) : le statut
n'est JAMAIS un cycle de vie pilote par l'utilisateur (pas de
`django-fsm-2`/`attempt_transition`) — c'est un champ calcule, derive de la
progression agregee des `StgKeyResult` rattaches, recalcule a chaque
ecriture d'un `StgKeyResult`/`StgCheckIn` (cf. `services/objectives.py::
recompute_objective_status`). Coherent avec la nature d'un indicateur de
pilotage plutot qu'un document metier soumis a un workflow d'approbation."""

from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models.base import BaseModel, ReferenceMixin

SECTOR_TEXTILE = "textile"
SECTOR_LEATHER = "cuir"
SECTOR_AGRIFOOD = "agroalimentaire"
SECTOR_IMPORT_EXPORT = "import_export"
SECTOR_CRAFT = "artisanat"

# Cadre multi-secteurs des maintenant (decision actee avec l'utilisateur) :
# 5 secteurs couverts par le referentiel, seul `textile` a des valeurs de
# benchmark reelles chargees (fixture `textile_mg.json`) — les 4 autres
# restent un cadre vide, rempli lors de la future extension sectorielle
# Madagascar (cf. plan).
SECTOR_CHOICES = [
    (SECTOR_TEXTILE, _("Textile")),
    (SECTOR_LEATHER, _("Cuir et maroquinerie")),
    (SECTOR_AGRIFOOD, _("Agroalimentaire")),
    (SECTOR_IMPORT_EXPORT, _("Import-export généraliste")),
    (SECTOR_CRAFT, _("Artisanat")),
]


class StgObjective(BaseModel, ReferenceMixin):
    LEVEL_COMPANY = "company"
    LEVEL_DEPARTMENT = "department"
    LEVEL_INDIVIDUAL = "individual"
    LEVEL_CHOICES = [
        (LEVEL_COMPANY, _("Entreprise")),
        (LEVEL_DEPARTMENT, _("Département")),
        (LEVEL_INDIVIDUAL, _("Individuel")),
    ]
    # Ordre de la cascade OKR — un objectif ne peut avoir pour parent qu'un
    # objectif de niveau egal ou superieur (jamais un individuel comme
    # parent d'un objectif d'entreprise), cf. `services/objectives.py`.
    LEVEL_ORDER = {LEVEL_COMPANY: 0, LEVEL_DEPARTMENT: 1, LEVEL_INDIVIDUAL: 2}

    STATUS_DRAFT = "draft"
    STATUS_ACTIVE = "active"
    STATUS_ON_TRACK = "on_track"
    STATUS_AT_RISK = "at_risk"
    STATUS_ACHIEVED = "achieved"
    STATUS_MISSED = "missed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, _("Brouillon")),
        (STATUS_ACTIVE, _("Actif")),
        (STATUS_ON_TRACK, _("En bonne voie")),
        (STATUS_AT_RISK, _("A risque")),
        (STATUS_ACHIEVED, _("Atteint")),
        (STATUS_MISSED, _("Manque")),
    ]

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    level = models.CharField(max_length=16, choices=LEVEL_CHOICES)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children"
    )
    owner = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # UUID, jamais de FK Django vers `apps.presence.models.PrsDepartment`
    # (regle de couplage n°1) — libelle resolu via le gap
    # `presence.services.public.get_department_display_name` si besoin.
    department_id = models.UUIDField(null=True, blank=True)
    sector_code = models.CharField(max_length=32, choices=SECTOR_CHOICES, blank=True)
    period_start = models.DateField()
    period_end = models.DateField()
    # Calcule automatiquement, jamais defini par l'utilisateur en dehors de
    # la creation (draft par defaut) — cf. docstring module.
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT)

    class Meta:
        db_table = "stg_objective"
        ordering = ["level", "period_start"]

    def __str__(self) -> str:
        return self.title


class StgKeyResult(BaseModel):
    objective = models.ForeignKey(
        StgObjective, on_delete=models.CASCADE, related_name="key_results"
    )
    # Nom d'indicateur libre mais destine a l'affichage — champ interface,
    # pas une donnee humaine libre comme `StgNote.body` : l'i18n concrete se
    # fait au niveau des libelles PROPOSES par le code (fixtures/formulaires),
    # le champ lui-meme reste un `CharField` (l'utilisateur choisit le nom
    # de son propre indicateur, souvent deja dans sa langue de travail).
    metric_name = models.CharField(max_length=150)
    target_value = models.DecimalField(max_digits=18, decimal_places=4)
    current_value = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal(0))
    unit = models.CharField(max_length=32, blank=True)
    # Texte libre optionnel — jamais valide contre une liste fermee de
    # modules (dette assumee : une faute de frappe donne juste un rafraichi-
    # ssement impossible, signale explicitement par
    # `services/objectives.py::refresh_key_result_from_source`, jamais un
    # echec silencieux).
    kpi_source_module = models.CharField(max_length=64, blank=True)
    kpi_source_function = models.CharField(max_length=128, blank=True)

    class Meta:
        db_table = "stg_key_result"

    def __str__(self) -> str:
        return self.metric_name

    def progress_pct(self) -> Decimal:
        """Progression bornee [0, 100] — `target_value == 0` est traite
        comme "atteint" des que `current_value > 0`, jamais une division par
        zero silencieuse."""
        if self.target_value == 0:
            return Decimal(100) if self.current_value > 0 else Decimal(0)
        pct = (self.current_value / self.target_value) * Decimal(100)
        return max(Decimal(0), min(pct, Decimal(100)))


class StgCheckIn(BaseModel):
    key_result = models.ForeignKey(StgKeyResult, on_delete=models.CASCADE, related_name="check_ins")
    date = models.DateField()
    value = models.DecimalField(max_digits=18, decimal_places=4)
    comment = models.TextField(blank=True)
    author = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "stg_check_in"
        ordering = ["-date"]

    def __str__(self) -> str:
        return f"{self.key_result.metric_name} @ {self.date}"


class StgSectorBenchmark(BaseModel):
    """Referentiel de standards par secteur (5 secteurs, cf. `SECTOR_CHOICES`
    ci-dessus), verse par date d'effet — meme patron que
    `core.RegulatoryParameter` (versionnement) mais modele dedie : la cle
    naturelle est composite (secteur + KPI), pas un simple code plat.

    **Reserve methodologique explicite** (meme discipline que
    `pcg2005_mg.json`/le bareme IRSA) : les valeurs chargees par la fixture
    `textile_mg.json` sont INDICATIVES, non validees par un expert sectoriel
    independant — jamais a presenter comme une verite sectorielle absolue."""

    sector_code = models.CharField(max_length=32, choices=SECTOR_CHOICES)
    kpi_code = models.CharField(max_length=64)
    kpi_label = models.CharField(max_length=150)
    target_min = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    target_max = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    unit = models.CharField(max_length=32, blank=True)
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "stg_sector_benchmark"
        ordering = ["sector_code", "kpi_code", "valid_from"]

    def __str__(self) -> str:
        return f"{self.sector_code}:{self.kpi_code}"


class StgNote(BaseModel):
    """Contenu narratif/editorial redige par un humain (direction) — `body`
    n'est PAS wrappe en `gettext` (contenu utilisateur dans sa propre langue
    de travail, pas un libelle d'interface, cf. convention du projet)."""

    objective = models.ForeignKey(
        StgObjective,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notes",
    )
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    author = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "stg_note"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title
