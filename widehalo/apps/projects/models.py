"""Module `projects` (Gestion de projets) — porte depuis l'ancienne version
WideHalo (Laravel, 19 fonctionnalites), reecrit pour ce socle Django
modulith. Cf. plan, section « Module `projects` (Gestion de projets) »,
sous-sequencement PJ1-PJ15. **PJ1+PJ2** : squelette d'app + les 2 modeles
de hierarchie unifiee (`PrjProject`, `PrjTask`, PJ1) + `PrjTaskDependency`
(PJ2, dependances entre taches/detection de cycle/Gantt SVG/chemin
critique CPM/endpoint PATCH drag-and-drop des dates) — les 12 modeles
restants (`PrjSprint`, `PrjBudgetLine`, `PrjTimeEntry`, `PrjTeamMember`,
`PrjCustomFieldDefinition`, `PrjWikiPage`, `PrjGuestAccess`, ...) arrivent
aux etapes PJ3-PJ14.

Dependances declarees (`module.py`) : `core`, `partners`, `accounting`,
`strategy` — mais **aucune n'est reellement consommee a ce stade** (regle
de couplage n1 : jamais de FK Django cross-app, uniquement `services.
public`) :
- `client_partner_id` (sur `PrjProject`) reste un simple `UUIDField`
  nullable, JAMAIS une FK vers `apps.partners.models.Partner` ni un appel
  a `partners.services.public` — aucun ecran de ce premier jalon n'exige
  encore de resoudre ce partenaire (validation/affichage reportes a une
  etape ulterieure, cf. plan).
- `linked_objective_id` (sur `PrjProject`) reste un simple `UUIDField`
  nullable, vers un futur `apps.strategy.models.StgObjective` — le gap
  `strategy.services.public` correspondant est explicitement reporte a
  PJ13 (« Liaison KPI/Stratégie »), cf. plan.
- La facturation multi-modes (`accounting.services.public.
  create_customer_invoice_from_source`) est reportee a PJ5.

**Decision de conception disclosed — champ `sprint` de `PrjTask`** : le
plan (§ modele `PrjTask`) mentionne un `sprint` FK nullable vers un futur
`PrjSprint` (modele introduit seulement a PJ6, "Backlog agile"). Ce modele
n'existe pas encore a PJ1. Deux options etaient possibles : (a) omettre
completement le champ maintenant et laisser PJ6 l'ajouter par une nouvelle
migration ; (b) ajouter des maintenant un `sprint_id` UUID nullable
"neutre" (comme `client_partner_id`/`linked_objective_id` ci-dessus), que
PJ6 remplacera par une vraie FK Django (puisque `PrjSprint` vivra dans la
MEME app `projects` — ce n'est PAS un gap inter-app, une FK directe est
donc le choix cible final, pas un `services.public`). **Choix retenu :
option (a), omission pure et simple du champ a ce stade** — plus simple a
faire evoluer sans migration a re-ecrire : PJ6 ajoutera directement
`sprint = models.ForeignKey("projects.PrjSprint", null=True, blank=True,
...)` par une migration additive (`AddField`), sans avoir a modifier ou
supprimer un `sprint_id` interimaire cree ici. Contrairement a
`client_partner_id`/`linked_objective_id` (reference vers une AUTRE app,
un UUID neutre restera definitivement le bon choix, jamais remplace par
une FK), `sprint` reference un modele de la MEME app qui n'existe
simplement pas encore chronologiquement — l'omission est donc strictement
plus simple que de poser un UUID neutre voue a etre remplace.

**Decision de conception disclosed — validation de hierarchie
`PrjTask.parent`** : ce module NE valide PAS a ce stade la coherence
semantique du couple (`task_type` du parent, `task_type` de l'enfant) —
ex. rien n'empeche aujourd'hui de rattacher un `epic` comme enfant d'un
`milestone`. La SEULE regle appliquee des PJ1 (`services/tasks.py::
create_task`) est structurelle : un `parent` doit appartenir au MEME
`project` que l'enfant (integrite de l'arborescence), et une tache ne peut
pas etre son propre parent. La validation semantique complete (un
`milestone` ne devrait jamais avoir d'enfants, un `epic` ne devrait jamais
avoir de parent, une sous-tache `task` ne devrait avoir qu'un parent
`epic` ou `task`) est explicitement REPORTEE a un chantier ulterieur
(candidat naturel : PJ2, en meme temps que `PrjTaskDependency`/detection
de cycle, deja dans le meme registre de coherence de graphe) — elle
n'est pas un pre-requis du squelette demande par PJ1."""

from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _
from django_fsm import FSMField, transition

from apps.core.models.base import BaseModel, ReferenceMixin


class PrjProject(BaseModel, ReferenceMixin):
    """Projet (document numerote, meme patron que `SalesOrder`/
    `FinLoanApplication`). Cycle de vie volontairement PAS une FSM
    `django-fsm-2` : `status`/`health` (on_track/at_risk/off_track) est un
    INDICATEUR derive de l'EVM (SPI/CPI), pas un etat de workflow lineaire
    a transitions gardees — meme discipline que `StgObjective.status`
    (`apps.strategy.models`), un champ recalcule par un futur service
    (PJ4/PJ13, EVM), jamais mute directement par l'utilisateur ni protege
    par des transitions. Pour l'instant (PJ1) c'est un simple champ
    editable, le calcul automatique n'existe pas encore."""

    METHODOLOGY_WATERFALL = "waterfall"
    METHODOLOGY_AGILE = "agile"
    METHODOLOGY_CHOICES = [
        (METHODOLOGY_WATERFALL, _("Cycle en cascade (waterfall)")),
        (METHODOLOGY_AGILE, _("Agile")),
    ]

    STATUS_ON_TRACK = "on_track"
    STATUS_AT_RISK = "at_risk"
    STATUS_OFF_TRACK = "off_track"
    STATUS_CHOICES = [
        (STATUS_ON_TRACK, _("Dans les temps")),
        (STATUS_AT_RISK, _("A risque")),
        (STATUS_OFF_TRACK, _("Hors trajectoire")),
    ]

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    # Jamais de FK Django vers `apps.partners.models.Partner` — cf.
    # docstring de module ci-dessus.
    client_partner_id = models.UUIDField(null=True, blank=True)
    methodology = models.CharField(
        max_length=16, choices=METHODOLOGY_CHOICES, default=METHODOLOGY_WATERFALL
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ON_TRACK)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    owner = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # Reference future vers `apps.strategy.models.StgObjective` (PJ13) —
    # UUID simple, jamais de FK, cf. docstring de module ci-dessus.
    linked_objective_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "prj_project"
        ordering = ["-created_at"]
        # PJ5 (facturation multi-modes) : la facturation est une operation
        # sensible (genere une ecriture comptable engageant le tenant vis a
        # vis d'un client) — meme discipline que `accounting.validate_
        # accmove`/`purchase.run_reordering` (permission personnalisee
        # dediee, PAS le simple `projects.change_prjproject` deja largement
        # distribue a tous les roles "domaine cible" de la gestion de
        # projet, cf. `ROLE_APP_PERMISSIONS`/`CUSTOM_PERMISSIONS` dans
        # `apps.core.services.rbac_policy`). Restreinte a `admin`/
        # `direction`/`resp_commercial` (cf. cette meme matrice) — pas
        # `resp_production`/`collaborateur`, qui gerent la production/les
        # taches mais ne sont pas habilites a engager une facturation
        # client.
        permissions = [("bill_prjproject", "Peut declencher la facturation d'un projet")]

    def __str__(self) -> str:
        return self.name


class PrjTask(BaseModel, ReferenceMixin):
    """Unifie epic/tache/sous-tache/jalon en UN SEUL modele via
    `task_type` — meme discipline d'economie de modeles deja appliquee
    dans ce depot (`MrpBomLineState` unique plutot que plusieurs modeles,
    `CatalogSectorSpec` generique plutot que 3 modeles par secteur, cf.
    plan). `state` porte un cycle de vie complet `django-fsm-2` (contrairement
    a `status` de `PrjProject` ci-dessus, qui n'est qu'un indicateur derive) :
    todo -> in_progress -> done, embranchements blocked (reversible vers
    in_progress) et cancelled (depuis n'importe quel etat non terminal) —
    meme patron `FSMField`/`@transition`/`attempt_transition()` que
    `MrpOrder`/`SalesOrder` (cf. `apps/mrp/models.py::MrpOrder`,
    `apps/mrp/services/orders.py`). **Piege documente a respecter par tout
    appelant** : `attempt_transition()` ne sauvegarde JAMAIS le champ FSM
    lui-meme — cf. `apps/core/services/workflow.py::attempt_transition` et
    le garde-fou AST `tests/architecture/
    test_attempt_transition_saves_state.py`."""

    TYPE_EPIC = "epic"
    TYPE_TASK = "task"
    TYPE_MILESTONE = "milestone"
    TYPE_CHOICES = [
        (TYPE_EPIC, _("Epic")),
        (TYPE_TASK, _("Tache")),
        (TYPE_MILESTONE, _("Jalon")),
    ]

    STATE_TODO = "todo"
    STATE_IN_PROGRESS = "in_progress"
    STATE_BLOCKED = "blocked"
    STATE_DONE = "done"
    STATE_CANCELLED = "cancelled"
    STATE_CHOICES = [
        (STATE_TODO, _("A faire")),
        (STATE_IN_PROGRESS, _("En cours")),
        (STATE_BLOCKED, _("Bloquee")),
        (STATE_DONE, _("Terminee")),
        (STATE_CANCELLED, _("Annulee")),
    ]

    task_type = models.CharField(max_length=16, choices=TYPE_CHOICES, default=TYPE_TASK)
    project = models.ForeignKey(PrjProject, on_delete=models.CASCADE, related_name="tasks")
    # Hierarchie (epic -> tache -> sous-tache) : cf. docstring de module
    # ci-dessus pour le niveau de validation applique a ce stade (PJ1,
    # structurel uniquement) vs reporte (semantique, PJ2).
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    # PJ6 ajoutera `sprint = FK("projects.PrjSprint", ...)` par migration
    # additive — cf. docstring de module ci-dessus (option (a) retenue :
    # champ omis a PJ1, pas de `sprint_id` UUID interimaire).
    assignee = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    state = FSMField(default=STATE_TODO, choices=STATE_CHOICES)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    # Pour le futur Gantt (PJ2) : duree en jours, saisie/calculee
    # independamment de start_date/end_date (permet un Gantt sans dates
    # fixees, patron classique d'ordonnancement relatif).
    duration_days = models.PositiveIntegerField(default=0)
    percent_complete = models.PositiveSmallIntegerField(default=0)
    # Calcule par un futur service CPM (PJ2, chemin critique) — jamais
    # mute directement par l'utilisateur au-dela de ce jalon. `False` par
    # defaut ici (aucun calcul CPM n'existe encore a PJ1).
    is_critical_path = models.BooleanField(default=False)
    # Pour le futur module agile (PJ6, backlog/velocite) — nullable :
    # seules les taches estimees en points (mode agile) le renseignent.
    story_points = models.PositiveSmallIntegerField(null=True, blank=True)
    # PJ5 (facturation par jalon, `services/billing.py::bill_by_milestone`) :
    # montant contractuel associe a un jalon (`task_type=milestone`),
    # facture en une fois une fois la tache `state=done`. Nullable/nul pour
    # toutes les taches non-jalon (champ non pertinent pour elles) ET pour
    # un jalon dont le montant n'a pas encore ete neglocie/saisi — un jalon
    # avec `budgeted_amount=None` est explicitement refuse a la facturation
    # (cf. `bill_by_milestone`), jamais un montant invente. **Decision
    # disclosed** : plutot qu'un nouveau modele dedie ("PrjMilestoneAmount"),
    # ou plutot que de deriver ce montant d'une `PrjBudgetLine` (qui n'a
    # aucun lien structurel avec une tache precise dans le modele actuel —
    # une ligne budgetaire est rattachee au PROJET, jamais a une tache), un
    # simple champ supplementaire sur `PrjTask` est le choix le plus
    # econome en modeles (cf. discipline d'economie de ce depot) : c'est la
    # SEULE donnee manquante pour honorer la facturation par jalon, un
    # champ scalaire suffit, une table dediee serait disproportionnee.
    budgeted_amount = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    # Valeurs libres a ce stade (PJ1) — seront validees contre un futur
    # `PrjCustomFieldDefinition` (PJ7), cf. plan.
    custom_fields = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "prj_task"
        ordering = ["project", "created_at"]

    def __str__(self) -> str:
        return f"{self.reference or self.id} — {self.get_task_type_display()}"

    @transition(field=state, source=STATE_TODO, target=STATE_IN_PROGRESS)
    def start(self) -> None:
        pass

    @transition(field=state, source=STATE_IN_PROGRESS, target=STATE_BLOCKED)
    def block(self) -> None:
        pass

    @transition(field=state, source=STATE_BLOCKED, target=STATE_IN_PROGRESS)
    def unblock(self) -> None:
        pass

    @transition(field=state, source=STATE_IN_PROGRESS, target=STATE_DONE)
    def finish(self) -> None:
        pass

    @transition(
        field=state,
        source=[STATE_TODO, STATE_IN_PROGRESS, STATE_BLOCKED],
        target=STATE_CANCELLED,
    )
    def cancel(self) -> None:
        pass


class PrjTaskDependency(BaseModel):
    """Dependance entre deux taches d'un MEME projet (PJ2). Le graphe forme
    par ce modele alimente deux services de `apps/projects/services/` :
    - `dependencies.py::add_dependency` : REFUSE explicitement (leve
      `ValidationError`, jamais une creation silencieuse suivie d'un crash
      ailleurs) toute dependance qui introduirait un cycle dans le graphe
      du projet — differenciateur documente au plan comme absent
      d'Asana/Monday/Jira/ClickUp.
    - `gantt.py::compute_critical_path` : algorithme CPM (Critical Path
      Method) classique, cf. docstring de ce module pour les hypotheses
      simplificatrices retenues en V1 (traitement de tout type de
      dependance comme `finish_to_start` pour le calcul du chemin
      critique lui-meme ; les autres types sont bien stockes/affiches
      dans le Gantt mais n'influencent pas encore le forward/backward
      pass mathematique — disclosed explicitement plutot qu'une fausse
      precision).

    `UniqueConstraint(from_task, to_task)` : empeche la duplication d'une
    MEME arete (une paire from/to ne peut porter qu'un seul enregistrement
    de dependance) — la detection de doublon applicative (message
    explicite avant meme d'atteindre la contrainte DB) vit dans
    `add_dependency`."""

    TYPE_FINISH_TO_START = "finish_to_start"
    TYPE_START_TO_START = "start_to_start"
    TYPE_FINISH_TO_FINISH = "finish_to_finish"
    TYPE_START_TO_FINISH = "start_to_finish"
    TYPE_CHOICES = [
        (TYPE_FINISH_TO_START, _("Fin -> Debut")),
        (TYPE_START_TO_START, _("Debut -> Debut")),
        (TYPE_FINISH_TO_FINISH, _("Fin -> Fin")),
        (TYPE_START_TO_FINISH, _("Debut -> Fin")),
    ]

    from_task = models.ForeignKey(
        PrjTask, on_delete=models.CASCADE, related_name="dependencies_out"
    )
    to_task = models.ForeignKey(PrjTask, on_delete=models.CASCADE, related_name="dependencies_in")
    dependency_type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, default=TYPE_FINISH_TO_START
    )

    class Meta:
        db_table = "prj_task_dependency"
        ordering = ["from_task", "to_task"]
        constraints = [
            models.UniqueConstraint(
                fields=["from_task", "to_task"], name="uniq_prj_task_dependency_pair"
            )
        ]

    def __str__(self) -> str:
        return f"{self.from_task_id} -> {self.to_task_id} ({self.dependency_type})"


class PrjBudgetLine(BaseModel):
    """Ligne budgetaire d'un projet (PJ4) — pas `ReferenceMixin` (meme
    raisonnement que `PrjTaskDependency` : une simple ligne d'un budget,
    aucun besoin de numero de document dedie). Alimente le service EVM
    (`apps/projects/services/evm.py`) :
    - `planned_amount` (somme -> `BAC`, Budget At Completion) et
      `actual_amount` (somme -> `AC`, Actual Cost) sont les deux entrees
      brutes du calcul EVM (SPI/CPI/EAC).
    - `category` (`capex`/`opex`) et `period` (mois de rattachement de la
      ligne) alimentent la courbe en S cumulee (`compute_s_curve`) —
      **`period` est toujours normalise au 1er jour du mois** par la
      courbe en S (granularite mensuelle unique en V1, cf. docstring de
      `services/evm.py`), mais la ligne elle-meme peut porter n'importe
      quelle date du mois concerne (pas de contrainte DB sur le jour).

    Montants toujours `Decimal` (jamais `float`), meme discipline stricte
    que le reste de ce projet (`DecimalField(max_digits=18,
    decimal_places=4)`, meme precision que `catalog`/`sales`)."""

    CATEGORY_CAPEX = "capex"
    CATEGORY_OPEX = "opex"
    CATEGORY_CHOICES = [
        (CATEGORY_CAPEX, _("Investissement (CAPEX)")),
        (CATEGORY_OPEX, _("Fonctionnement (OPEX)")),
    ]

    project = models.ForeignKey(PrjProject, on_delete=models.CASCADE, related_name="budget_lines")
    category = models.CharField(max_length=8, choices=CATEGORY_CHOICES, default=CATEGORY_OPEX)
    label = models.CharField(max_length=255)
    planned_amount = models.DecimalField(max_digits=18, decimal_places=4)
    actual_amount = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    # Mois/date de rattachement de la ligne — utilise par la courbe en S
    # (`services/evm.py::compute_s_curve`) pour regrouper/cumuler les
    # montants par mois calendaire.
    period = models.DateField()

    class Meta:
        db_table = "prj_budget_line"
        ordering = ["project", "period", "category"]

    def __str__(self) -> str:
        return f"{self.label} ({self.get_category_display()}, {self.period})"


class PrjInvoicingRecord(BaseModel):
    """Trace de facturation projet (PJ5, `services/billing.py`) — 225e/250
    modele de ce depot, budget encore respecte. **Decision de modelisation
    disclosed** : un nouveau modele dedie a ete prefere a l'alternative
    "champs additionnels sur `PrjProject`/`PrjTask`" (ex. `invoiced_amount`/
    `is_invoiced`) parce que les 4 modes de facturation n'ont PAS la meme
    cardinalite d'evenements a tracer :
    - jalon : potentiellement PLUSIEURS jalons par projet, chacun facture
      UNE fois (verification "deja facture" par TACHE, pas par projet) ;
    - avancement : facturation INCREMENTALE repetee (l'ecart depuis la
      DERNIERE facturation par avancement, necessite l'HISTORIQUE complet
      des montants deja factures par ce mode, pas un simple booleen) ;
    - forfait : une SEULE fois par projet (verification "deja facture" par
      PROJET) ;
    - regie (T&M, PJ8) : facturation potentiellement PERIODIQUE (une ligne
      par periode facturee), meme besoin d'historique que l'avancement.
    Un champ scalaire unique par entite (ex. `PrjProject.is_invoiced`) ne
    peut pas representer cette diversite (surtout le cumul incremental de
    l'avancement, qui a structurellement besoin d'une SOMME sur plusieurs
    enregistrements passes) sans multiplier les champs ad hoc (un jeu de
    champs `milestone_invoiced`/`fixed_invoiced`/`percentage_invoiced_total`
    disperses sur 2 modeles differents) — un seul modele d'audit normalise,
    interrogeable par `project`/`task`/`mode`, est strictement plus simple
    et plus econome au global qu'une demi-douzaine de champs eparpilles.
    Sert egalement de piste d'audit (qui a facture, quand, pour combien) —
    utile independamment du seul besoin anti-double-facturation.

    `invoice_id` : UUID simple vers l'`AccMove` cree par `accounting.
    services.public.create_customer_invoice_from_source` — JAMAIS une FK
    Django cross-app (regle de couplage n°1, meme discipline que
    `client_partner_id`/`linked_objective_id` de `PrjProject`)."""

    MODE_MILESTONE = "milestone"
    MODE_PERCENTAGE = "percentage"
    MODE_TIME_AND_MATERIAL = "time_and_material"
    MODE_FIXED = "fixed"
    MODE_CHOICES = [
        (MODE_MILESTONE, _("Jalon")),
        (MODE_PERCENTAGE, _("Pourcentage d'avancement")),
        (MODE_TIME_AND_MATERIAL, _("Regie temps & materiel")),
        (MODE_FIXED, _("Forfait")),
    ]

    project = models.ForeignKey(
        PrjProject, on_delete=models.CASCADE, related_name="invoicing_records"
    )
    # Renseigne uniquement pour le mode `milestone` (le jalon facture) —
    # `null=True` pour les 3 autres modes, qui facturent au niveau du
    # PROJET, pas d'une tache precise.
    task = models.ForeignKey(
        PrjTask,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="invoicing_records",
    )
    mode = models.CharField(max_length=20, choices=MODE_CHOICES)
    amount = models.DecimalField(max_digits=18, decimal_places=4)
    # UUID simple vers `apps.accounting.models.AccMove` — jamais une FK
    # cross-app, cf. docstring de classe.
    invoice_id = models.UUIDField()
    billed_date = models.DateField()
    billed_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "prj_invoicing_record"
        ordering = ["-billed_date", "-created_at"]

    def __str__(self) -> str:
        return f"{self.project_id} — {self.get_mode_display()} — {self.amount}"
