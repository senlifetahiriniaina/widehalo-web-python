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
    # Cahier Phase 2 §13.3, STR-1 : « chaque résultat clé est adossé à un
    # indicateur du dictionnaire [gouverné, `apps.analytics.
    # AnMetricDefinition`] avec sa cible et son échéance ; l'avancement se
    # calcule, il ne se déclare pas. » Référence le CODE d'un indicateur
    # PUBLIÉ du dictionnaire — `blank=True` uniquement pour compatibilité
    # ascendante avec les `StgKeyResult` créés avant ce chantier (jamais
    # blanc pour un résultat clé créé désormais, cf.
    # `services/objectives.py::add_key_result`, qui l'exige). Un résultat
    # clé adossé à un indicateur se rafraîchit via `services/objectives.py
    # ::refresh_key_result_from_dictionary` — jamais via un `StgCheckIn`
    # manuel, qui reste réservé aux résultats clés SANS indicateur
    # gouverné (compatibilité ascendante, cf. `kpi_source_module` ci-
    # dessous, mécanisme antérieur toujours actif pour eux).
    metric_code = models.CharField(max_length=64, blank=True)
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


class StgBudget(BaseModel):
    """Budget versionné et verrouillable (cahier §13.3, STR-3/STR-4).

    **Immuabilité des chiffres engagés (STR-3, §17.2 « y compris pour un
    administrateur »)** : une fois `is_locked=True`, `lines`/`name`/
    `period_*`/`source_*`/`version`/`previous_version` deviennent
    immuables — pas seulement côté service Python, un trigger Postgres
    (migration dédiée, même patron que `AccMove`/RG-ACC-2) rejette toute
    tentative en base, y compris un appel direct à l'API ou une
    modification manuelle. `variance_comments` reste volontairement
    modifiable après verrouillage (cf. docstring de la migration : STR-6
    exige un commentaire de gestion sur un écart constaté APRÈS
    verrouillage, pendant la revue). Une révision des chiffres crée une
    NOUVELLE ligne (`version` incrémenté, `previous_version` pointant vers
    l'ancienne, TOUJOURS non verrouillée à la création) — jamais une
    modification en place.

    `lines`/`variance_comments` en JSON plutôt que des modèles dédiés
    (simplification assumée et disclosée, économie de 2 modèles sur le
    budget d'architecture) :
    - `lines` : ``[{"axis_type": "famille"|"point_vente"|"compte",
      "axis_value": str, "metric_code": str, "period": "YYYY-MM-DD",
      "budgeted_value": str(Decimal)}, ...]`` — `metric_code` référence
      TOUJOURS un indicateur du dictionnaire gouverné (STR-5 : l'écart
      doit comparer la même définition des deux côtés).
    - `variance_comments` : ``[{"line_key": str, "author_id": str, "at":
      iso, "text": str}, ...]`` — `line_key` = concaténation stable
      `axis_type:axis_value:period` d'une ligne ci-dessus (STR-6, un
      commentaire est rattaché À LA LIGNE, jamais à un document séparé)."""

    SOURCE_MANUAL = "manual"
    SOURCE_SIMULATION = "simulation_scenario"
    SOURCE_FORECAST = "forecast_publication"
    SOURCE_CHOICES = [
        (SOURCE_MANUAL, _("Saisie manuelle")),
        (SOURCE_SIMULATION, _("Scénario de simulation")),
        (SOURCE_FORECAST, _("Prévision publiée")),
    ]

    name = models.CharField(max_length=200)
    period_start = models.DateField()
    period_end = models.DateField()
    source_type = models.CharField(max_length=24, choices=SOURCE_CHOICES, default=SOURCE_MANUAL)
    # Référence de la source d'initialisation (STR-4 : « conservation de la
    # référence et de la version de la source ») — {"scenario_id": str}
    # ou {"publication_version": int, "published_at": iso}. Vide pour
    # `SOURCE_MANUAL`.
    source_reference = models.JSONField(default=dict, blank=True)
    version = models.PositiveIntegerField(default=1)
    previous_version = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="revisions"
    )
    is_locked = models.BooleanField(default=False)
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    lines = models.JSONField(default=list, blank=True)
    variance_comments = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "stg_budget"
        ordering = ["name", "-version"]

    def __str__(self) -> str:
        return f"{self.name} v{self.version}"


class StgInitiative(BaseModel):
    """Action rattachée à un objectif (écran « Initiatives et plans
    d'action », cahier §13.3) — le chatter (« réutilise... le chatter de la
    Phase 1 ») n'est PAS un champ ici : un canal `apps.chat.ChatChannel`
    générique est ouvert à la demande sur cette instance via
    `apps.chat.services.public.get_or_create_document_channel`, même
    mécanisme que n'importe quel autre document métier du dépôt. **Pas de
    moteur de workflow/approbation** (simplification assumée et
    disclosée) : l'écran ne décrit que des champs d'état simples
    (« responsable, échéance, état, avancement »), pas une validation
    formelle — `apps.core.services.workflow` (ApprovalRule) reste
    disponible pour une extension future si un besoin réel apparaît."""

    STATE_NOT_STARTED = "not_started"
    STATE_IN_PROGRESS = "in_progress"
    STATE_DONE = "done"
    STATE_BLOCKED = "blocked"
    STATE_CHOICES = [
        (STATE_NOT_STARTED, _("Non démarrée")),
        (STATE_IN_PROGRESS, _("En cours")),
        (STATE_DONE, _("Terminée")),
        (STATE_BLOCKED, _("Bloquée")),
    ]

    objective = models.ForeignKey(
        StgObjective, on_delete=models.CASCADE, related_name="initiatives"
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    due_date = models.DateField(null=True, blank=True)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_NOT_STARTED)
    progress_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal(0))

    class Meta:
        db_table = "stg_initiative"
        ordering = ["objective", "due_date"]

    def __str__(self) -> str:
        return self.title


class StgReviewPack(BaseModel):
    """Pack de revue figé et horodaté (cahier §13.3, STR-7 : « affiche
    exactement les mêmes valeurs, les mêmes définitions et les mêmes
    commentaires qu'à sa génération »). Immuable dès la création — AUCUNE
    étape de verrouillage distincte (contrairement à `StgBudget`) : un
    trigger Postgres (même migration que `StgBudget`) rejette toute
    modification de `snapshot`/`period_start`/`period_end`/`budget`, y
    compris pour un administrateur ; seuls les champs de bibliothèque
    `is_active`/`archived_at` (soft-delete, retrait de la liste) restent
    modifiables.

    `snapshot` (JSONField) fige tout ce qui doit rester identique à la
    réouverture : ``{"objectives": [...valeurs+définitions des indicateurs
    à cette date...], "variance_lines": [...écarts+commentaires...],
    "risks": [...cartographie à cette date...]}``."""

    budget = models.ForeignKey(
        StgBudget, null=True, blank=True, on_delete=models.PROTECT, related_name="review_packs"
    )
    period_start = models.DateField()
    period_end = models.DateField()
    generated_at = models.DateTimeField()
    generated_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "stg_review_pack"
        ordering = ["-generated_at"]

    def __str__(self) -> str:
        return f"Pack de revue {self.period_start:%Y-%m} — {self.generated_at:%Y-%m-%d}"


class StgRisk(BaseModel):
    """Cartographie des risques d'entreprise (cahier §13.3, STR-8) — liée
    aux objectifs (`linked_objective`, optionnel) comme le demande le
    cadrage. `last_reassessed_at`/`last_reassessed_by` changent à chaque
    réévaluation ; le journal d'audit capture automatiquement CE
    changement comme toute autre écriture (`StgRisk` hérite de
    `BaseModel`, cf. `apps.core.audit_signals`) — aucun mécanisme dédié à
    construire ici pour satisfaire « toute réévaluation apparaît au
    journal d'audit »."""

    PROBABILITY_CHOICES = [(i, str(i)) for i in range(1, 6)]
    IMPACT_CHOICES = [(i, str(i)) for i in range(1, 6)]

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    linked_objective = models.ForeignKey(
        StgObjective, null=True, blank=True, on_delete=models.SET_NULL, related_name="risks"
    )
    probability = models.PositiveSmallIntegerField(choices=PROBABILITY_CHOICES)
    impact = models.PositiveSmallIntegerField(choices=IMPACT_CHOICES)
    control_measure = models.TextField(blank=True)
    owner = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    last_reassessed_at = models.DateTimeField(null=True, blank=True)
    last_reassessed_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "stg_risk"
        ordering = ["-probability", "-impact"]

    def __str__(self) -> str:
        return self.title

    @property
    def risk_score(self) -> int:
        return self.probability * self.impact
