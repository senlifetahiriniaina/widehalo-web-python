"""Contrat public de l'app `bi` — seule surface que les autres apps métier
(le futur module WhatsApp, cahier Phase 2 §13.4, au premier chef — "les
diffuse" dans la chaîne BI→Forecast→Strategy→WhatsApp du résumé exécutif)
ont le droit d'importer (cf. tests/architecture/test_module_boundaries.py).
Aucun consommateur réel dans ce lot — même discipline que `pos.services.
public`/`analytics.services.public` à leur livraison initiale."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.bi.models import BiReport

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User


def list_report_catalog(tenant: Tenant) -> list[dict[str, Any]]:
    """Catalogue des rapports publiés — primitives uniquement, jamais
    l'objet `BiReport` (règle de couplage n°1)."""
    return [
        {"code": report.code, "name": report.name, "domaine": report.domaine}
        for report in BiReport.objects.filter(tenant=tenant, is_published=True)
    ]


def get_report_result(tenant: Tenant, code: str, user: User) -> dict[str, Any] | None:
    """Exécute un rapport publié POUR `user` (cf. `services/query.py::
    run_report`, droits appliqués avant agrégation) — `None` si le rapport
    n'existe pas ou n'est pas publié."""
    from apps.bi.services.query import run_report

    report = BiReport.objects.filter(tenant=tenant, code=code, is_published=True).first()
    if report is None:
        return None
    return run_report(tenant, report, user)
