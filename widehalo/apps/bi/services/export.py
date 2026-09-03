"""Passerelle vers `apps.reporting` (BI-8 : export asynchrone) — enregistre
UN SEUL rapport générique `REPORT_CODE` au démarrage (`apps.py::ready()`),
dont les `params` désignent le `BiReport` précis à exporter. Réutilise
entièrement `RptJob`/`generate_report` (cf. `apps.reporting.services.
public.enqueue_report_generation`) plutôt que de construire un second
mécanisme de job — voir docstring de `apps.bi.models` pour le
raisonnement complet."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.bi.models import BiReport
from apps.bi.services.query import run_report
from apps.core.tenant_context import activate_tenant

if TYPE_CHECKING:
    from apps.core.models.user import User

REPORT_CODE = "bi.dynamic_report"


def render_bi_report_rows(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    """Callback `render_rows` enregistré dans `core.services.
    reports_registry` — appelé par `apps.reporting.services.engine.
    _run_job_sync`, potentiellement en dehors de tout contexte tenant déjà
    activé (job asynchrone) : recherche le `BiReport` via `all_objects`
    (même discipline que `apps.core.services.email_change`, recherche par
    identifiant non devinable hors contexte tenant), puis active
    explicitement son tenant pour l'exécution de la requête elle-même."""
    if actor is None:
        return []
    report = BiReport.all_objects.filter(id=params.get("bi_report_id")).first()
    if report is None:
        return []
    with activate_tenant(report.tenant_id):
        result = run_report(report.tenant, report, actor)
    rows: list[dict[str, Any]] = []
    for code, payload in result["metrics"].items():
        for row in payload["rows"]:
            rows.append({"indicateur": code, "unite": payload["unite"], **row})
    return rows
