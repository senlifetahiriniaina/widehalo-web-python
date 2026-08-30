"""Registre central des verifications d'anomalies cross-modules (module
`ai`, chantier « Detection d'anomalies cross-modules ») — meme patron que
`apps.core.services.reports_registry`/`automation_registry`. Chaque module
metier enregistre un adaptateur MINCE vers une verification DETERMINISTE
deja construite ailleurs dans ce depot (ex. ecart budgetaire `accounting`,
exception de stock negatif `stocks`, conflit de planification `projects`) —
`apps.ai` ne reimplemente JAMAIS de regle metier, il se contente d'executer
les fonctions enregistrees et de persister leurs resultats.

**La detection elle-meme n'est jamais confiee a un LLM** — seule une
narrative optionnelle en prose (resume humain-lisible d'une anomalie deja
detectee) peut etre generee par IA, cf. `apps.ai.services.anomaly_
detection`. Coherent avec la discipline « explicabilite d'abord » deja
appliquee dans ce depot (ex. PAY-M1, MRP-FPY1)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

SEVERITY_LOW = "faible"
SEVERITY_MEDIUM = "moyenne"
SEVERITY_HIGH = "haute"


@dataclass(frozen=True)
class AnomalyCandidate:
    """Un candidat d'anomalie DEJA detecte par une fonction deterministe
    d'un module metier — `ai` ne fait que le persister (`AiAnomaly`)."""

    content_type_label: str  # "app_label.modelname", ex. "accounting.accbudgetline"
    object_id: str
    severity: str
    description: str


# Une fonction de verification recoit un tenant_id et renvoie la liste des
# anomalies qu'elle a deja detectees deterministiquement pour ce tenant —
# jamais un appel LLM a l'interieur de cette fonction.
AnomalyCheckFunction = Callable[[str], list[AnomalyCandidate]]


@dataclass(frozen=True)
class RegisteredAnomalyCheck:
    code: str
    module: str
    label: str
    function: AnomalyCheckFunction


_REGISTRY: dict[str, RegisteredAnomalyCheck] = {}


def register_anomaly_check(
    code: str, *, module: str, label: str, function: AnomalyCheckFunction
) -> None:
    """Appele depuis `apps.py::ready()` de chaque module metier. Idempotent
    (un meme `code` re-enregistre remplace simplement l'entree)."""
    _REGISTRY[code] = RegisteredAnomalyCheck(
        code=code, module=module, label=label, function=function
    )


def get_anomaly_check(code: str) -> RegisteredAnomalyCheck | None:
    return _REGISTRY.get(code)


def list_anomaly_checks() -> list[RegisteredAnomalyCheck]:
    return sorted(_REGISTRY.values(), key=lambda c: c.code)


def registry_size() -> int:  # pragma: no cover - utilitaire de diagnostic
    return len(_REGISTRY)
