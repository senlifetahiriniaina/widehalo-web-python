"""5 fonctions d'assistance IA du module `projects` (PJ12) — chacune
s'appuie EXCLUSIVEMENT sur `apps.core.services.ai_assistant.get_ai_provider`
(jamais un acces HTTP direct depuis cette app, meme discipline "un seul
point d'appel reseau potentiel du module" que `apps.purchase.services.
price_watch`). Le mecanisme generique (stub par defaut, connecteur reel
optionnel) est documente dans `apps.core.services.ai_assistant` — pas
duplique ici.

**Discipline commune aux 5 fonctions, disclosee explicitement** : quand
`get_ai_provider()` retourne le stub (configuration absente — cas par
defaut de tout environnement dev/test/prod tant que l'utilisateur n'a pas
rempli `settings.AI_PROVIDER_CONFIG`), chaque fonction retourne quand meme
une reponse coherente et EXPLICITEMENT etiquetee "assistance IA non
configuree" — jamais une exception, jamais un texte qui se ferait passer
pour une vraie analyse. Meme chose si le connecteur reel est configure
mais echoue (`AIProviderError`, ex. panne reseau transitoire du
fournisseur) : degrade vers un message clair plutot que de faire planter
l'appelant (meme discipline que `PriceQuote.price=None` sur echec reseau).

**Aucune de ces fonctions n'ecrit en base a partir d'une sortie LLM non
verifiee** — decision disclosee, coherente avec la prudence deja actee
ailleurs dans ce chantier (cf. docstrings ci-dessous pour le detail par
fonction) :
- `identify_risks` retourne du texte pour revue humaine — PAS de creation
  automatique de `RiskItem` (un humain reste responsable d'appeler
  `apps.projects.services.public.flag_project_risk` pour les risques
  qu'il juge fondes) ;
- `generate_tasks_from_spec` retourne une liste de propositions (`dict`),
  PAS de creation automatique de `PrjTask` (un appelant UI/API qui accepte
  une proposition boucle explicitement sur `apps.projects.services.
  tasks.create_task`)."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Any

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.services.ai_assistant import AIProviderError, get_ai_provider
from apps.projects.models import PrjProject, PrjTask, PrjTaskDependency
from apps.projects.services.evm import compute_evm_snapshot

_AI_NOT_CONFIGURED_LABEL = _(
    "[Assistance IA non configuree] Analyse indicative basee uniquement sur "
    "les donnees calculees ci-dessous — configurer settings.AI_PROVIDER_CONFIG "
    "pour une synthese redigee."
)


def _safe_complete(prompt: str, *, max_tokens: int = 500) -> str:
    """Point d'appel unique vers le provider IA pour ce module — capture
    `AIProviderError` (panne d'un connecteur reel configure) et degrade
    vers un message clair, jamais une exception qui remonterait a
    l'appelant metier (meme discipline que `_safe_complete`-like patterns
    deja utilises ailleurs dans ce depot pour un service externe
    optionnel)."""
    provider = get_ai_provider()
    try:
        return provider.complete(prompt, max_tokens=max_tokens)
    except AIProviderError as exc:
        return str(
            _("[Connecteur IA indisponible : %(error)s] Reponse non generee.") % {"error": str(exc)}
        )


@dataclass(frozen=True)
class TaskDurationEstimate:
    """Resultat de `estimate_task_duration` — `is_ai_generated=False`
    signifie que la reponse provient du stub (pas de connecteur IA
    configure), jamais une estimation chiffree inventee dans ce cas."""

    estimate_text: str
    is_ai_generated: bool
    similar_tasks_sample_size: int


def _similar_completed_tasks(task: PrjTask) -> list[PrjTask]:
    """Taches DEJA terminees du meme projet et du meme `task_type`, pour
    donner un point de comparaison chiffre au prompt (duree reelle passee
    = `duration_days`, plutot que de ne fournir aucun ancrage a l'IA)."""
    return list(
        PrjTask.objects.filter(
            project_id=task.project_id,
            task_type=task.task_type,
            state=PrjTask.STATE_DONE,
        )
        .exclude(id=task.id)
        .order_by("-updated_at")[:10]
    )


def estimate_task_duration(task: PrjTask) -> TaskDurationEstimate:
    """PJ12-1 : estime la duree d'une tache a partir de ses attributs
    (titre/description/type/story points) et des durees REELLES de taches
    similaires deja terminees dans le meme projet (`_similar_completed_
    tasks`) — jamais un chiffre invente sans ancrage aux donnees du
    projet."""
    similar = _similar_completed_tasks(task)
    if not similar:
        similar_summary = str(_("Aucune tache similaire terminee dans ce projet."))
    else:
        durations = ", ".join(str(t.duration_days) for t in similar)
        similar_summary = str(
            _(
                "Durees reelles (jours) de %(count)d taches similaires "
                "deja terminees : %(durations)s."
            )
            % {"count": len(similar), "durations": durations}
        )

    # `PrjTask` ne porte ni `title` ni `description` (cf. `models.py`) —
    # seuls `reference`/`task_type`/`custom_fields`/`story_points` sont
    # disponibles comme signal descriptif, jamais un champ invente.
    instruction = _(
        "Estime la duree necessaire (en jours) pour la tache suivante et justifie brievement."
    )
    prompt = (
        f"{instruction}\n"
        f"{_('Reference')}: {task.reference or task.id}\n"
        f"{_('Type')}: {task.get_task_type_display()}\n"
        f"{_('Champs personnalises')}: {task.custom_fields or '-'}\n"
        f"{_('Points d effort (story points)')}: {task.story_points or '-'}\n"
        f"{similar_summary}"
    )
    provider = get_ai_provider()
    is_stub = provider.__class__.__name__ == "StubAIProvider"
    text = _safe_complete(prompt)
    if is_stub:
        text = f"{_AI_NOT_CONFIGURED_LABEL} {similar_summary}"
    return TaskDurationEstimate(
        estimate_text=text,
        is_ai_generated=not is_stub,
        similar_tasks_sample_size=len(similar),
    )


def _overdue_tasks(project: PrjProject, *, today: dt.date) -> list[PrjTask]:
    return list(
        PrjTask.objects.filter(project=project, end_date__lt=today)
        .exclude(state__in=[PrjTask.STATE_DONE, PrjTask.STATE_CANCELLED])
        .order_by("end_date")
    )


def _assignee_overlap_conflicts(project: PrjProject) -> list[tuple[PrjTask, PrjTask]]:
    """Chevauchements de dates entre taches DU PROJET partageant le meme
    `assignee` — meme logique de comparaison que `apps.projects.services.
    conflicts.dates_overlap`, reappliquee ici au perimetre "projet" plutot
    qu'au perimetre "utilisateur" de `detect_scheduling_conflicts`
    (celle-ci est parametree par `user`, pas par `project` — cf.
    `services/conflicts.py`)."""
    from apps.projects.services.conflicts import dates_overlap

    tasks = [
        t
        for t in PrjTask.objects.filter(project=project, assignee__isnull=False)
        .exclude(state__in=[PrjTask.STATE_DONE, PrjTask.STATE_CANCELLED])
        .order_by("start_date")
        if t.start_date and t.end_date
    ]
    conflicts: list[tuple[PrjTask, PrjTask]] = []
    for i, task_a in enumerate(tasks):
        # Garanti par le filtre `if t.start_date and t.end_date` ci-dessus.
        assert task_a.start_date and task_a.end_date
        for task_b in tasks[i + 1 :]:
            assert task_b.start_date and task_b.end_date
            if task_a.assignee_id == task_b.assignee_id and dates_overlap(
                task_a.start_date, task_a.end_date, task_b.start_date, task_b.end_date
            ):
                conflicts.append((task_a, task_b))
    return conflicts


def _evm_health_summary(project: PrjProject) -> str:
    snapshot = compute_evm_snapshot(project)
    if snapshot.spi is None or snapshot.cpi is None:
        return str(_("EVM non calculable (dates de projet ou taches actives insuffisantes)."))
    return str(
        _("SPI=%(spi)s CPI=%(cpi)s (< 0.95 = signal de derive planning/budget).")
        % {"spi": snapshot.spi, "cpi": snapshot.cpi}
    )


def identify_risks(project: PrjProject) -> str:
    """PJ12-2 : synthetise en prose les risques du projet a partir de
    SIGNAL REEL calcule (conflits d'affectation, taches en retard, sante
    EVM) — jamais une hallucination sans ancrage. Retourne du TEXTE pour
    revue humaine, ne cree JAMAIS automatiquement de `RiskItem` (cf.
    docstring de module : decision disclosee de prudence, un humain reste
    responsable d'appeler `apps.projects.services.public.flag_project_
    risk` pour les risques qu'il juge fondes apres lecture)."""
    today = timezone.now().date()
    overdue = _overdue_tasks(project, today=today)
    conflicts = _assignee_overlap_conflicts(project)
    evm_summary = _evm_health_summary(project)

    signal_lines = [
        str(_("Taches en retard : %(count)d.") % {"count": len(overdue)}),
        str(
            _("Conflits d'affectation (chevauchement de dates) : %(count)d.")
            % {"count": len(conflicts)}
        ),
        evm_summary,
    ]
    signal_summary = " ".join(signal_lines)

    instruction = _(
        "A partir des signaux suivants, redige une synthese des risques du "
        "projet et des actions recommandees."
    )
    prompt = f"{instruction}\n{signal_summary}"
    provider = get_ai_provider()
    if provider.__class__.__name__ == "StubAIProvider":
        return f"{_AI_NOT_CONFIGURED_LABEL} {signal_summary}"
    return _safe_complete(prompt, max_tokens=800)


def generate_status_report(project: PrjProject) -> str:
    """PJ12-3 : rapport d'avancement en prose (progression, sante
    budgetaire EVM, blocages) pour relecture/edition par un chef de
    projet avant diffusion — jamais envoye automatiquement (aucun appel a
    `notify_project_owner` ici, une decision de diffusion reste humaine)."""
    today = timezone.now().date()
    tasks = PrjTask.objects.filter(project=project)
    total = tasks.count()
    done = tasks.filter(state=PrjTask.STATE_DONE).count()
    blocked = tasks.filter(state=PrjTask.STATE_BLOCKED).count()
    overdue = _overdue_tasks(project, today=today)
    evm_summary = _evm_health_summary(project)

    signal_summary = str(
        _(
            "Taches : %(done)d/%(total)d terminees, %(blocked)d bloquees, "
            "%(overdue)d en retard. %(evm)s"
        )
        % {
            "done": done,
            "total": total,
            "blocked": blocked,
            "overdue": len(overdue),
            "evm": evm_summary,
        }
    )

    instruction = _(
        "Redige un rapport d etat de projet concis (progression, sante "
        "budgetaire, blocages) a partir de ces donnees."
    )
    prompt = f"{instruction}\n{_('Projet')}: {project.name}\n{signal_summary}"
    provider = get_ai_provider()
    if provider.__class__.__name__ == "StubAIProvider":
        return f"{_AI_NOT_CONFIGURED_LABEL} {signal_summary}"
    return _safe_complete(prompt, max_tokens=800)


def generate_tasks_from_spec(project: PrjProject, spec_text: str) -> list[dict[str, Any]]:
    """PJ12-4 : decompose un texte libre de specification en propositions
    de taches (`title`/`description`/`story_points`). Retourne des
    DONNEES (`list[dict]`), ne cree JAMAIS de `PrjTask` (cf. docstring de
    module) — un appelant UI/API qui accepte une proposition doit boucler
    explicitement sur `apps.projects.services.tasks.create_task`.

    Sans connecteur IA configure (stub), retourne une liste VIDE plutot
    qu'une decomposition inventee — il n'existe aucune heuristique fiable
    pour "deviner" des taches a partir d'un texte libre sans modele de
    langage, contrairement a `identify_risks`/`generate_status_report`
    qui peuvent s'appuyer sur du signal deja calcule en base."""
    provider = get_ai_provider()
    if provider.__class__.__name__ == "StubAIProvider":
        return []

    instruction = _(
        "Decompose la specification suivante en taches. Reponds en JSON : "
        "une liste d objets avec les cles title, description, story_points (entier)."
    )
    prompt = f"{instruction}\n{_('Projet')}: {project.name}\n{_('Specification')}: {spec_text}"
    raw = _safe_complete(prompt, max_tokens=1500)
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []

    proposals: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict) or "title" not in item:
            continue
        story_points = item.get("story_points")
        proposals.append(
            {
                "title": str(item["title"]),
                "description": str(item.get("description", "")),
                "story_points": int(story_points) if isinstance(story_points, int) else None,
            }
        )
    return proposals


def suggest_prioritization(project: PrjProject) -> str:
    """PJ12-5 : suggere un ordre de priorite des taches ouvertes en prose,
    a partir d'echeances, de dependances (`PrjTaskDependency`) et de la
    criticite (`PrjTask.is_critical_path`, calculee par `apps.projects.
    services.gantt.compute_critical_path`) — signal REEL, pas une
    reordonnance inventee."""
    open_tasks = list(
        PrjTask.objects.filter(project=project)
        .exclude(state__in=[PrjTask.STATE_DONE, PrjTask.STATE_CANCELLED])
        .order_by("end_date", "created_at")
    )
    dependency_count = PrjTaskDependency.objects.filter(from_task__project=project).count()
    critical_count = sum(1 for t in open_tasks if t.is_critical_path)

    lines = [
        str(_("Taches ouvertes : %(count)d.") % {"count": len(open_tasks)}),
        str(_("Sur le chemin critique : %(count)d.") % {"count": critical_count}),
        str(_("Dependances declarees sur le projet : %(count)d.") % {"count": dependency_count}),
    ]
    for task in open_tasks[:20]:
        lines.append(
            str(
                _("- %(reference)s (echeance %(due)s, critique=%(critical)s)")
                % {
                    "reference": task.reference or str(task.id),
                    "due": task.end_date or "-",
                    "critical": task.is_critical_path,
                }
            )
        )
    signal_summary = "\n".join(lines)

    instruction = _(
        "Propose un ordre de priorite pour ces taches ouvertes, avec "
        "justification, en tenant compte des echeances/dependances/criticite."
    )
    prompt = f"{instruction}\n{signal_summary}"
    provider = get_ai_provider()
    if provider.__class__.__name__ == "StubAIProvider":
        return f"{_AI_NOT_CONFIGURED_LABEL} {signal_summary}"
    return _safe_complete(prompt, max_tokens=800)


__all__ = [
    "TaskDurationEstimate",
    "estimate_task_duration",
    "identify_risks",
    "generate_status_report",
    "generate_tasks_from_spec",
    "suggest_prioritization",
]
