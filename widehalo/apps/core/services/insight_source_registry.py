"""Registre central des sources d'insights proactifs cross-modules (module
`ai`, chantier AI5 « Insights proactifs automatises ») — meme patron exact
que `apps.core.services.anomaly_registry`/`reports_registry`/
`automation_registry`. Chaque module metier enregistre un adaptateur MINCE
vers une donnee DEJA calculee ailleurs dans ce depot (ex. tendance
saisonniere de demande `sales`, perspective de charge `strategy`, volume
d'absences `presence`) — `apps.ai` ne calcule JAMAIS de nouvelle
statistique/regle metier, il se contente d'executer les fonctions
enregistrees et de persister leurs resultats (`AiInsight`).

**Un insight n'est jamais decide par un LLM** — seule une synthese
optionnelle en prose (observation qualitative reliant plusieurs insights
deterministes DEJA generes dans le meme run) peut etre generee par IA, cf.
`apps.ai.services.automated_insights`. Coherent avec la discipline
« explicabilite d'abord » deja appliquee dans ce chantier
(`anomaly_registry`)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class InsightCandidate:
    """Un candidat d'insight DEJA calcule par une fonction deterministe
    d'un module metier — `ai` ne fait que le persister (`AiInsight`)."""

    category: str
    title: str
    body: str
    # Le plus souvent un seul module (celui qui enregistre la source) ;
    # plus d'un uniquement pour un candidat authentiquement issu d'une
    # correlation cross-module deja calculee par le module lui-meme.
    source_modules: list[str] = field(default_factory=list)


# Une fonction de source recoit un tenant_id et renvoie la liste des
# insights qu'elle a deja calcules deterministiquement pour ce tenant —
# jamais un appel LLM a l'interieur de cette fonction.
InsightSourceFunction = Callable[[str], list[InsightCandidate]]


@dataclass(frozen=True)
class RegisteredInsightSource:
    code: str
    module: str
    label: str
    function: InsightSourceFunction


_REGISTRY: dict[str, RegisteredInsightSource] = {}


def register_insight_source(
    code: str, *, module: str, label: str, function: InsightSourceFunction
) -> None:
    """Appele depuis `apps.py::ready()` de chaque module metier. Idempotent
    (un meme `code` re-enregistre remplace simplement l'entree)."""
    _REGISTRY[code] = RegisteredInsightSource(
        code=code, module=module, label=label, function=function
    )


def get_insight_source(code: str) -> RegisteredInsightSource | None:
    return _REGISTRY.get(code)


def list_insight_sources() -> list[RegisteredInsightSource]:
    return sorted(_REGISTRY.values(), key=lambda c: c.code)


def registry_size() -> int:  # pragma: no cover - utilitaire de diagnostic
    return len(_REGISTRY)
