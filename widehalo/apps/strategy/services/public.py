"""Contrat public de l'app `strategy` — seule surface qu'une autre app
aurait le droit d'importer (cf. tests/architecture/test_module_boundaries.py).

**PJ13 (`projects`, "Liaison KPI/Strategie")** : premier gap de LECTURE
reellement consomme par un autre module — `get_objective_summary` expose
le libelle/statut/key results d'un `StgObjective` a `projects.services.
public.get_linked_objective_summary`, qui le combine a l'EVM du projet
(`projects.services.evm.compute_evm_snapshot`) pour le widget KPI de
l'ecran detail projet. Meme discipline "jamais d'exception, `None` sur
configuration/reference absente ou etrangere" que `accounting.services.
public.get_financial_ratios_summary` (filtre explicite sur `tenant`,
l'appelant venant d'un AUTRE module n'est pas necessairement dans le
contexte HTTP tenant-scope de `TenantManager`)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.core.models.tenant import Tenant
from apps.strategy.models import StgObjective


def get_objective_summary(tenant: Tenant, objective_id: str | UUID) -> dict[str, Any] | None:
    """Passe-plat de lecture — aucun calcul, `StgObjective.status` est deja
    un champ calcule (cf. docstring de module de `apps.strategy.models`,
    `services/objectives.py::recompute_objective_status`), les `StgKeyResult.
    progress_pct()` sont deja une methode existante du modele, jamais
    redupliquee ici. Retourne `None` (jamais une exception) si
    `objective_id` ne correspond a aucun `StgObjective` ACTIF de CE
    `tenant` — meme discipline "jamais de faux positif" que `accounting.
    services.public.get_financial_ratios_summary`/`sales.services.public.
    get_delivered_qty_for_order` : un `objective_id` etranger au tenant
    appelant (ou une reference perimee/mal saisie cote `projects.
    PrjProject.linked_objective_id`, simple UUID neutre jamais valide
    contre `strategy` a l'ecriture, cf. sa docstring de modele) ne doit
    jamais laisser fuiter un objectif d'un AUTRE tenant."""
    objective = StgObjective.objects.filter(id=objective_id, tenant=tenant, is_active=True).first()
    if objective is None:
        return None
    key_results = objective.key_results.filter(is_active=True).order_by("metric_name")
    return {
        "id": str(objective.id),
        "title": objective.title,
        "status": objective.status,
        "level": objective.level,
        "period_start": objective.period_start.isoformat(),
        "period_end": objective.period_end.isoformat(),
        "key_results": [
            {
                "id": str(kr.id),
                "metric_name": kr.metric_name,
                "target_value": kr.target_value,
                "current_value": kr.current_value,
                "unit": kr.unit,
                "progress_pct": kr.progress_pct(),
            }
            for kr in key_results
        ],
    }
