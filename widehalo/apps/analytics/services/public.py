"""Contrat public de l'app `analytics` — seule surface que les autres apps
métier (le futur module `bi`, cahier Phase 2 §13.1, au premier chef) ont le
droit d'importer (cf. tests/architecture/test_module_boundaries.py).
Aucun consommateur réel dans ce lot (fondations, cf. `module.py`) — même
discipline que `pos.services.public` à sa livraison initiale."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db.models import Sum

from apps.analytics.models import AnMetricDefinition, AnRefreshRun, AnWarehouseState
from apps.analytics.services.dictionary import list_metric_history, list_metrics_for_user
from apps.analytics.services.fact_specs import FACT_SPECS

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User

_ALLOWED_FILTER_OPS = {"eq": "exact", "gte": "gte", "lte": "lte", "in": "in"}


def get_warehouse_state(tenant: Tenant) -> dict[str, Any] | None:
    """État courant de l'entrepôt (verrou, dernier rafraîchissement réussi)
    — primitives uniquement, jamais l'objet `AnWarehouseState`. `None` si
    aucun rafraîchissement n'a encore jamais été lancé pour ce tenant."""
    state = AnWarehouseState.objects.filter(tenant=tenant).first()
    if state is None:
        return None
    return {
        "is_locked": state.is_locked,
        "last_successful_refresh_at": state.last_successful_refresh_at,
    }


def list_published_metrics(tenant: Tenant, user: User) -> list[dict[str, Any]]:
    """Dictionnaire d'indicateurs publiés et autorisés pour `user` (cf.
    `services/dictionary.py::list_metrics_for_user`) — primitives
    uniquement, jamais l'objet `AnMetricDefinition`."""
    return [
        {
            "code": metric.code,
            "libelle": metric.libelle,
            "unite": metric.unite,
            "module_source": metric.module_source,
            "axes_autorises": metric.axes_autorises,
            "maille_minimale": metric.maille_minimale,
        }
        for metric in list_metrics_for_user(tenant, user)
    ]


def get_metric_definition(tenant: Tenant, code: str) -> dict[str, Any] | None:
    """Détail d'un indicateur du dictionnaire (`None` si absent) — AUCUN
    filtrage par rôle ici (contrairement à `list_published_metrics`) :
    destiné à un appelant qui a déjà validé les droits de l'utilisateur
    courant (ex. le moteur de requête guidé du futur module BI, une fois
    l'indicateur choisi dans une liste déjà filtrée)."""
    metric = AnMetricDefinition.objects.filter(tenant=tenant, code=code, is_current=True).first()
    if metric is None:
        return None
    return {
        "code": metric.code,
        "libelle": metric.libelle,
        "description": metric.description,
        "formule": metric.formule,
        "unite": metric.unite,
        "module_source": metric.module_source,
        "axes_autorises": metric.axes_autorises,
        "roles_autorises": metric.roles_autorises,
        "maille_minimale": metric.maille_minimale,
        "statut": metric.statut,
        "version": metric.version,
    }


def list_metric_versions(tenant: Tenant, code: str) -> list[dict[str, Any]]:
    """Historique complet d'un indicateur (BI-9, « conserve la
    précédente ») — primitives uniquement, la version courante en
    premier."""
    return [
        {
            "version": metric.version,
            "libelle": metric.libelle,
            "formule": metric.formule,
            "is_current": metric.is_current,
            "updated_at": metric.updated_at,
        }
        for metric in list_metric_history(tenant, code)
    ]


def get_latest_refresh_summary(tenant: Tenant) -> dict[str, Any] | None:
    """Dernière exécution de rafraîchissement de l'entrepôt (BI-4 :
    « dernière exécution, durée, volume, échec... visible sur chaque
    tableau de bord ») — primitives uniquement. `None` si aucune
    exécution n'a encore eu lieu."""
    run = AnRefreshRun.objects.filter(tenant=tenant).order_by("-started_at").first()
    if run is None:
        return None
    duration_seconds = (
        (run.finished_at - run.started_at).total_seconds() if run.finished_at else None
    )
    return {
        "started_at": run.started_at,
        "status": run.status,
        "duration_seconds": duration_seconds,
        "rows_processed": run.rows_processed,
        "error_message": run.error_message,
        "reconciliation_ok": run.reconciliation_ok,
    }


def _django_filters(spec_dimension_fields: dict[str, str], filters: list[dict[str, Any]]) -> dict[str, Any]:
    django_filters: dict[str, Any] = {}
    for entry in filters:
        dimension = entry.get("dimension")
        op = entry.get("op")
        if dimension not in spec_dimension_fields or op not in _ALLOWED_FILTER_OPS:
            continue
        lookup = f"{spec_dimension_fields[dimension]}__{_ALLOWED_FILTER_OPS[op]}"
        django_filters[lookup] = entry.get("value")
    return django_filters


def aggregate_fact(
    tenant: Tenant, *, fact: str, dimensions: list[str], filters: list[dict[str, Any]]
) -> list[dict[str, Any]] | None:
    """Agrégat `Sum()` sur un fait de l'entrepôt (moteur de requête guidé
    du module BI, §13.1, BI-2) — `fact` doit être un des noms déclarés dans
    `services/fact_specs.py`, `dimensions`/`filters` ne référencent jamais
    autre chose que les codes d'axe abstraits qui y sont déclarés (jamais
    un lookup ORM ni du SQL fourni par l'appelant). `None` si `fact` est
    inconnu. Une dimension/un filtre demandé mais non déclaré pour ce fait
    est silencieusement ignoré, jamais une exception (même discipline
    "périmètre qui s'adapte" que `apps.bi.services.query`)."""
    spec = FACT_SPECS.get(fact)
    if spec is None:
        return None
    qs = spec.queryset_factory(tenant).filter(**_django_filters(spec.dimension_fields, filters))
    dims = [d for d in dimensions if d in spec.dimension_fields]
    lookups = [spec.dimension_fields[d] for d in dims]
    if not lookups:
        total = qs.aggregate(value=Sum(spec.value_field))["value"]
        return [{"value": total or 0}]
    qs = qs.values(*lookups).annotate(value=Sum(spec.value_field)).order_by(*lookups)
    return [
        {**{d: row[spec.dimension_fields[d]] for d in dims}, "value": row["value"] or 0} for row in qs
    ]


def detail_fact(
    tenant: Tenant, *, fact: str, filters: list[dict[str, Any]], limit: int = 200
) -> list[dict[str, Any]] | None:
    """Lignes de détail d'un fait (BI-10, exploration du détail) — mêmes
    garde-fous que `aggregate_fact`. `None` si `fact` est inconnu."""
    spec = FACT_SPECS.get(fact)
    if spec is None:
        return None
    qs = spec.queryset_factory(tenant).filter(**_django_filters(spec.dimension_fields, filters))
    fields = ["id", spec.value_field, *spec.detail_extra_fields]
    return list(qs.values(*fields).order_by("-created_at")[:limit])
