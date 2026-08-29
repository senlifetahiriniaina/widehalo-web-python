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
