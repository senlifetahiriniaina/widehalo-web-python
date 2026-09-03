"""Contrat public de l'app `bi` — seule surface que les autres apps métier
(le module `strategy`, cahier Phase 2 §13.3 — STR-1/STR-5, un résultat
clé/une ligne de budget adossés à un indicateur du dictionnaire ; le futur
module WhatsApp, §13.4, "les diffuse" dans la chaîne BI→Forecast→
Strategy→WhatsApp du résumé exécutif) ont le droit d'importer (cf.
tests/architecture/test_module_boundaries.py)."""

from __future__ import annotations

from decimal import Decimal
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


def get_metric_current_value(tenant: Tenant, code: str, user: User) -> Decimal | None:
    """Valeur agrégée courante (totale, sans ventilation) d'UN indicateur
    du dictionnaire gouverné — utilisé par `strategy` (STR-1 : « chaque
    résultat clé est adossé à un indicateur... l'avancement se calcule,
    il ne se déclare pas » ; STR-5 : l'écart budgétaire doit comparer la
    MÊME définition que le réel, donc passer par CE calcul et aucun autre).
    `None` si l'indicateur est inconnu, non publié, non autorisé pour le
    rôle de `user`, ou non raccordé à un fait calculable (mêmes
    garde-fous que `services/query.py::run_report`, jamais dupliqués)."""
    from apps.bi.services.metric_computers import METRIC_FACTS
    from apps.bi.services.query import _is_metric_authorized, _user_role_codes
    from apps.analytics.services.public import aggregate_fact, get_metric_definition

    metric = get_metric_definition(tenant, code)
    if metric is None or not _is_metric_authorized(metric, _user_role_codes(user)):
        return None
    fact = METRIC_FACTS.get(code)
    if fact is None:
        return None
    rows = aggregate_fact(tenant, fact=fact, dimensions=[], filters=[])
    if not rows:
        return None
    value = rows[0]["value"]
    return value if isinstance(value, Decimal) else Decimal(str(value))
