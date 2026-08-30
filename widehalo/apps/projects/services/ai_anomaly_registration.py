"""AI3 : auto-enregistrement d'une verification d'anomalie DETERMINISTE
du module `projects` dans `core.services.anomaly_registry`, appele depuis
`apps.py::ready()` — meme patron que `ai_context_registration.
register_ai_context()`/`automation_registration.register_actions()` deja
etablis dans ce module.

**Adaptateur mince, pas une nouvelle regle metier** : `_check_scheduling_
conflicts` reutilise tel quel `services.conflicts.detect_scheduling_
conflicts(user)` (PJ3, deja construit) — jamais un nouveau calcul de
chevauchement de dates invente ici.

**Adaptation de signature (disclosed)** : `detect_scheduling_conflicts`
prend un `User`, pas un tenant — cette verification n'a donc pas de sens
"pour tout le tenant" sans une notion d'utilisateurs a parcourir.
Simplification assumee : on ne parcourt que les utilisateurs ayant une
affectation active a au moins un projet du tenant (`PrjTeamMember`,
deja construit par PJ7), pas TOUS les `core.User` du systeme (qui peuvent
appartenir a d'autres tenants ou n'avoir jamais touche ce module) — un
cout de requete borne, cible sur les utilisateurs reellement actifs sur
des projets de CE tenant."""

from __future__ import annotations

from apps.core.models.user import User
from apps.core.services.anomaly_registry import (
    SEVERITY_MEDIUM,
    AnomalyCandidate,
    register_anomaly_check,
)
from apps.projects.models import PrjTeamMember
from apps.projects.services.conflicts import detect_scheduling_conflicts


def _check_scheduling_conflicts(tenant_id: str) -> list[AnomalyCandidate]:
    candidates: list[AnomalyCandidate] = []
    user_ids = (
        PrjTeamMember.objects.filter(tenant_id=tenant_id)
        .values_list("user_id", flat=True)
        .distinct()
    )

    for user_id in user_ids:
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:  # pragma: no cover - incoherence de donnees improbable
            continue

        for conflict in detect_scheduling_conflicts(user):
            candidates.append(
                AnomalyCandidate(
                    content_type_label="projects.prjtask",
                    object_id=str(conflict.task_b.id),
                    severity=SEVERITY_MEDIUM,
                    description=(
                        f"Conflit de planification pour {user.email} : la tache "
                        f"'{conflict.task_b.reference or conflict.task_b.id}' "
                        f"({conflict.task_b.start_date} -> {conflict.task_b.end_date}) "
                        f"chevauche la tache "
                        f"'{conflict.task_a.reference or conflict.task_a.id}' "
                        f"({conflict.task_a.start_date} -> {conflict.task_a.end_date})."
                    ),
                )
            )
    return candidates


def register_ai_anomaly_checks() -> None:
    register_anomaly_check(
        "projects.scheduling_conflict",
        module="projects",
        label="Conflit de planification (double affectation)",
        function=_check_scheduling_conflicts,
    )
