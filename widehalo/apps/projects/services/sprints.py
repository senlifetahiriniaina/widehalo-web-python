"""Service sprints agiles (PJ6, "Backlog agile") — cf. plan, section
« Module `projects` », etape PJ6. Comble le gap explicitement annonce
depuis PJ1 dans la docstring de `models.py` (champ `PrjTask.sprint`,
omis a PJ1, ajoute par ce chantier).

Couvre : creation/demarrage/cloture de sprint (avec la regle metier "un
seul sprint actif a la fois par projet"), lecture du backlog (taches sans
sprint), calcul du burndown et de la velocite.

**Source de donnees du burndown — decision disclosee** : `PrjTask` ne
porte aucun historique de changement d'etat DATE directement sur lui-meme
(seul `state` REEL courant est stocke). `apps.core.models.workflow.
StateTransitionLog` (Lot 1, etape 8) EST exploitable : il journalise
automatiquement (signal `django_fsm.post_transition`, cf. `apps.core.
workflows`) CHAQUE transition reussie de `PrjTask.state`, horodatee
(`created_at`), par `content_type`/`object_id` — c'est un historique reel,
pas une simplification. `compute_burndown` l'exploite donc pour
reconstituer, JOUR PAR JOUR, l'etat de chaque tache du sprint tel qu'il
etait CE JOUR-LA (pas l'etat actuel projete sur toute la periode), ce qui
est strictement plus fidele. **Limitation neanmoins disclosee** : ce
calcul suppose que l'ensemble des taches actuellement rattachees au sprint
(`sprint.tasks`) est reste STABLE tout au long du sprint (aucune tache
ajoutee/retiree du sprint en cours de route n'est reconstituee
retroactivement — `PrjTask.sprint` lui-meme n'est pas trace par
`StateTransitionLog`, qui ne couvre que le champ FSM `state`). Une tache
creee APRES le jour calcule est logiquement absente de ce jour (`created_
at` du `PrjTask` fait foi), mais un changement de RATTACHEMENT de sprint
(sans changement d'etat) n'est pas visible retroactivement — disclosure
volontaire plutot qu'une fausse precision inventee."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db.models import QuerySet, Sum
from django.utils.translation import gettext as _

from apps.core.models.workflow import StateTransitionLog
from apps.projects.models import PrjProject, PrjSprint, PrjTask

_DONE_OR_CANCELLED = {PrjTask.STATE_DONE, PrjTask.STATE_CANCELLED}


def create_sprint(
    project: PrjProject,
    *,
    name: str,
    start_date: dt.date,
    end_date: dt.date,
    goal: str = "",
) -> PrjSprint:
    if end_date < start_date:
        raise ValidationError(
            _("La date de fin du sprint doit etre posterieure a la date de debut.")
        )
    return PrjSprint.objects.create(
        tenant=project.tenant,
        project=project,
        name=name,
        start_date=start_date,
        end_date=end_date,
        goal=goal,
    )


def start_sprint(sprint: PrjSprint) -> PrjSprint:
    """Demarre un sprint `planned` -> `active`. Refuse explicitement (leve
    `ValidationError`) si un AUTRE sprint du meme projet est deja `active`
    — un seul sprint actif a la fois par projet (regle metier standard
    agile), verifiee applicativement (pas de contrainte DB, cf. docstring
    de `PrjSprint`)."""
    already_active = (
        PrjSprint.objects.filter(project=sprint.project_id, status=PrjSprint.STATUS_ACTIVE)
        .exclude(id=sprint.id)
        .first()
    )
    if already_active is not None:
        raise ValidationError(
            _(
                "Le sprint « %(name)s » est deja actif sur ce projet — "
                "un seul sprint actif a la fois."
            )
            % {"name": already_active.name}
        )
    sprint.status = PrjSprint.STATUS_ACTIVE
    sprint.save(update_fields=["status"])
    return sprint


def complete_sprint(sprint: PrjSprint) -> PrjSprint:
    """Cloture un sprint `active`/`planned` -> `completed`. **Decision
    disclosee sur le sort des taches non terminees** : deux options
    existaient (a) les detacher automatiquement du sprint (`sprint=None`,
    elles retournent au backlog) ou (b) les laisser rattachees avec leur
    `state` visible tel quel (le sprint cloture devient un instantane figé
    incluant ses taches non finies). **Choix retenu : option (a)** — c'est
    la version la plus simple ET la plus conforme a la pratique agile
    standard ("report au backlog" en fin de sprint, cf. enonce de la
    tache) : une tache `done`/`cancelled` reste rattachee (utile pour la
    velocite, cf. `compute_velocity`), toute autre tache est detachee
    (`sprint=None`) et redevient visible dans `get_backlog`."""
    PrjTask.objects.filter(sprint=sprint).exclude(state__in=_DONE_OR_CANCELLED).update(sprint=None)
    sprint.status = PrjSprint.STATUS_COMPLETED
    sprint.save(update_fields=["status"])
    return sprint


def get_backlog(project: PrjProject) -> QuerySet[PrjTask]:
    """Taches du projet SANS sprint assigne, hors `cancelled`/`done`
    (une tache deja terminee/annulee n'a plus sa place au backlog, qu'elle
    ait ou non ete rattachee a un sprint dans le passe)."""
    return project.tasks.filter(is_active=True, sprint__isnull=True).exclude(
        state__in=_DONE_OR_CANCELLED
    )


def _state_as_of(task_id: UUID, as_of: dt.date) -> str:
    """Reconstruit l'etat FSM d'une tache tel qu'il etait a la date `as_of`,
    a partir de `StateTransitionLog` (transitions reussies uniquement,
    `was_refused=False`) — dernier `to_state` dont la transition a eu lieu
    au plus tard le `as_of` (compare en date, pas en datetime, pour
    raisonner "jour par jour" comme le reste de cette fonction). Si aucune
    transition n'est encore survenue au plus tard cette date, la tache est
    reputee dans son etat INITIAL (`STATE_TODO`, valeur par defaut du
    champ) — l'appelant garantit deja que la tache EXISTAIT a cette date
    (`created_at <= as_of`, verifie avant d'appeler cette fonction)."""
    content_type = ContentType.objects.get_for_model(PrjTask)
    last = (
        StateTransitionLog.objects.filter(
            content_type=content_type, object_id=str(task_id), was_refused=False
        )
        .filter(created_at__date__lte=as_of)
        .order_by("-created_at")
        .first()
    )
    return last.to_state if last is not None else PrjTask.STATE_TODO


def compute_burndown(sprint: PrjSprint) -> list[dict[str, Any]]:
    """Serie temporelle jour par jour entre `sprint.start_date` et
    `sprint.end_date` : `story_points` restants (somme des `story_points`
    des taches du sprint dont l'etat, RECONSTITUE via `StateTransitionLog`
    a cette date-la (cf. `_state_as_of` et la docstring de module pour la
    limitation disclosee), n'est pas `done`. `cancelled` compte egalement
    comme "retire" (points ne comptant plus dans le restant, coherent avec
    `get_backlog`/`_DONE_OR_CANCELLED`). Taches sans `story_points` (valeur
    `None`) : comptees pour 0 point, jamais une valeur inventee."""
    tasks = list(sprint.tasks.filter(is_active=True))
    day_count = (sprint.end_date - sprint.start_date).days
    series: list[dict[str, Any]] = []
    for offset in range(day_count + 1):
        day = sprint.start_date + dt.timedelta(days=offset)
        remaining = Decimal("0")
        for task in tasks:
            points = task.story_points or 0
            if not points:
                continue
            created_date = task.created_at.date()
            if created_date > day:
                continue
            state = _state_as_of(task.id, day)
            if state not in _DONE_OR_CANCELLED:
                remaining += points
        series.append({"date": day, "story_points_remaining": remaining})
    return series


def compute_velocity(project: PrjProject, *, last_n_sprints: int = 5) -> Decimal:
    """Moyenne des `story_points` completes (taches `done`) par sprint, sur
    les `last_n_sprints` DERNIERS sprints `completed` du projet (tries par
    `end_date` decroissante). `Decimal("0")` si aucun sprint `completed`
    n'existe encore (jamais une division par zero, meme discipline que
    `services/evm.py::_ratio_or_none`)."""
    sprints = list(
        project.sprints.filter(is_active=True, status=PrjSprint.STATUS_COMPLETED).order_by(
            "-end_date"
        )[:last_n_sprints]
    )
    if not sprints:
        return Decimal("0")
    total = Decimal("0")
    for sprint in sprints:
        completed_points = (
            sprint.tasks.filter(is_active=True, state=PrjTask.STATE_DONE).aggregate(
                total=Sum("story_points")
            )["total"]
            or 0
        )
        total += Decimal(completed_points)
    return (total / len(sprints)).quantize(Decimal("0.01"))
