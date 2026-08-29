"""AUTO3 (chantier Studio de workflow visuel) — modeles de l'app
`automation`, dependance declaree UNIQUEMENT sur `core` (cf.
`apps/automation/module.py`) : jamais un import d'un autre module metier,
chaque module s'auto-enregistre dans `core.services.automation_registry`
depuis son propre `apps.py::ready()`.

**Distinction structurante `canvas_layout` (AutoFlow) vs `AutoStep`** : le
canevas visuel (bibliotheque JS vendorisee, AUTO5) exporte un JSON brut
(positions des noeuds, connexions dessinees) qui est persiste TEL QUEL
dans `AutoFlow.canvas_layout` mais reste OPAQUE au moteur d'execution — il
n'est jamais lu par `apps.automation.services.engine`. A la sauvegarde,
une fonction de COMPILATION dediee (AUTO5,
`apps.automation.services.compiler`) traduit ce layout visuel vers le
graphe REELLEMENT execute, porte par `AutoStep`/`next_step`/
`next_step_on_false`. Ce decouplage est le point de couture architectural
entre "ce que l'utilisateur a dessine" et "ce que le moteur execute" —
delibere, pas un oubli."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models.base import BaseModel, ReferenceMixin
from apps.core.models.event import EventLog

STEP_TYPE_CONDITION = "condition"
STEP_TYPE_ACTION = "action"
STEP_TYPE_CHOICES = [
    (STEP_TYPE_CONDITION, _("Condition")),
    (STEP_TYPE_ACTION, _("Action")),
]

RUN_STATUS_RUNNING = "running"
RUN_STATUS_SUCCESS = "success"
RUN_STATUS_FAILED = "failed"
RUN_STATUS_PARTIAL = "partial"
RUN_STATUS_CHOICES = [
    (RUN_STATUS_RUNNING, _("En cours")),
    (RUN_STATUS_SUCCESS, _("Succes")),
    (RUN_STATUS_FAILED, _("Echec")),
    (RUN_STATUS_PARTIAL, _("Partiel")),
]

RUN_STEP_STATUS_PENDING = "pending"
RUN_STEP_STATUS_SUCCESS = "success"
RUN_STEP_STATUS_FAILED = "failed"
RUN_STEP_STATUS_CHOICES = [
    (RUN_STEP_STATUS_PENDING, _("En attente")),
    (RUN_STEP_STATUS_SUCCESS, _("Succes")),
    (RUN_STEP_STATUS_FAILED, _("Echec")),
]


class AutoFlow(BaseModel, ReferenceMixin):
    """Un flux d'automatisation : declencheur (`trigger_event_type`,
    valide contre `core.events.PUBLISHED_EVENT_TYPES`, cf.
    `apps.automation.services.flows.create_flow` — jamais une chaine libre
    non verifiee) + filtre optionnel + graphe executable (`AutoStep`)."""

    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    trigger_event_type = models.CharField(max_length=100, db_index=True)
    # Condition JSON optionnelle evaluee via `core.services.expr.safe_eval`
    # sur le payload de l'evenement recu — `{}`/vide = toujours declenche.
    # Forme : {"expression": "payload['amount'] > 1000"}.
    trigger_filter = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=False)
    # Export brut du canevas visuel (AUTO5) — OPAQUE au moteur d'execution,
    # cf. docstring de module ci-dessus. Jamais utilise par `engine.py`.
    canvas_layout = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "auto_flow"

    def __str__(self) -> str:
        return f"{self.reference} — {self.name}"


class AutoStep(BaseModel):
    """Un noeud du graphe EXECUTABLE d'un flux — `condition` ou `action`.
    Le premier noeud du graphe est celui qu'aucun autre `AutoStep` de ce
    flux ne reference via `next_step`/`next_step_on_false` (cf.
    `apps.automation.services.engine.find_entry_step`), jamais un champ
    `is_entry` redondant a maintenir."""

    flow = models.ForeignKey(AutoFlow, on_delete=models.CASCADE, related_name="steps")
    step_type = models.CharField(max_length=16, choices=STEP_TYPE_CHOICES)
    # `condition` : {"expression": "..."} evalue via core.services.expr.
    # `action`    : {"action_code": "core.notify_role", "param_mapping":
    #                {"role_code": "direction", "notification_type": "...",
    #                 "payload": {"amount": "payload['amount']"}}}
    # `param_mapping` : chaque valeur est SOIT une valeur statique (JSON),
    # SOIT une expression `core.services.expr` prefixee `"="` (ex.
    # `"=payload['amount']"`) resolue contre le payload de l'evenement —
    # convention disclosed, cf. `apps.automation.services.engine.
    # resolve_param_mapping`.
    config = models.JSONField(default=dict, blank=True)
    next_step = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # Uniquement pertinent pour `step_type="condition"` — branche prise si
    # la condition est fausse (ou si son evaluation echoue, cf. engine.py).
    next_step_on_false = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "auto_step"

    def __str__(self) -> str:
        return f"{self.flow.name} / {self.step_type}"


class AutoRun(BaseModel):
    """Une execution d'`AutoFlow`, declenchee par un evenement du bus
    interne.

    **Reference a l'evenement declencheur** : `EventLog` (`core_event_log`)
    est un modele CONCRET, jamais une cible polymorphe — une ForeignKey
    directe est donc utilisee ici, PAS une paire generique
    `content_type`/`object_id` (reservee aux relations reellement
    polymorphes, cf. `apps.core.models.workflow.StateTransitionLog`).
    Verifie sur l'entite reelle avant de coder, comme demande par le plan,
    plutot que suppose."""

    flow = models.ForeignKey(AutoFlow, on_delete=models.CASCADE, related_name="runs")
    triggering_event = models.ForeignKey(
        EventLog, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    status = models.CharField(max_length=16, choices=RUN_STATUS_CHOICES, default=RUN_STATUS_RUNNING)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "auto_run"

    def __str__(self) -> str:
        return f"{self.flow.name} #{self.id} ({self.status})"


class AutoRunStep(BaseModel):
    """Trace d'execution d'un `AutoStep` au sein d'un `AutoRun` — meme
    discipline que `pay_payslip_line` (chaque etape garde sa base/resultat,
    jamais une boite noire) : auditable etape par etape."""

    run = models.ForeignKey(AutoRun, on_delete=models.CASCADE, related_name="steps")
    step = models.ForeignKey(AutoStep, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(
        max_length=16, choices=RUN_STEP_STATUS_CHOICES, default=RUN_STEP_STATUS_PENDING
    )
    result = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    retry_count = models.PositiveSmallIntegerField(default=0)
    executed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "auto_run_step"

    def __str__(self) -> str:
        return f"{self.run_id} / {self.step_id} ({self.status})"
