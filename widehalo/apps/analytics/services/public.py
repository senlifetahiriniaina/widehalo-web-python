"""Contrat public de l'app `analytics` — seule surface que les autres apps
métier (le module `bi`, cahier Phase 2 §13.1, et le module `forecast`,
§13.2, au premier chef) ont le droit d'importer (cf. tests/architecture/
test_module_boundaries.py)."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.db.models import Sum
from django.db.models.functions import TruncMonth

from apps.analytics.models import (
    AnDimTiers,
    AnFactEncaissement,
    AnFactTicketPos,
    AnFactVente,
    AnMetricDefinition,
    AnRefreshRun,
    AnWarehouseState,
)
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


def _django_filters(
    spec_dimension_fields: dict[str, str], filters: list[dict[str, Any]]
) -> dict[str, Any]:
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
        {**{d: row[spec.dimension_fields[d]] for d in dims}, "value": row["value"] or 0}
        for row in qs
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


_SALES_SERIES_DIMENSION_FIELDS = {
    "famille": "dim_article__categorie_nom",
    "article": "dim_article__reference",
    "client": "dim_tiers__nom",
}


def get_sales_value_series(
    tenant: Tenant, *, dimension_type: str, dimension_value: str, periods: int = 36
) -> list[dict[str, Any]]:
    """Série mensuelle de chiffre d'affaires HT pour une valeur de
    dimension (module `forecast`, cahier Phase 2 §13.2, FOR-8 : « ventes
    intègre POS + facturées, sans double comptage ») — fusionne `AnFactVente`
    (vente directe) et `AnFactTicketPos` (POS) sans risque de double
    comptage : ce sont deux flux documentaires disjoints dans ce dépôt (un
    ticket POS n'est jamais converti en `SalesOrder`, cf. `apps.pos.module`)
    plutôt que deux vues du même document.

    `dimension_type` parmi "famille"/"article"/"client"/"canal" ; pour
    "canal", `dimension_value` vaut "vente_directe" (n'agrège que
    `AnFactVente`) ou "pos" (n'agrège que `AnFactTicketPos`). Retourne les
    `periods` derniers mois, du plus ancien au plus récent, mois sans
    vente inclus avec `value=Decimal(0)` (jamais un trou silencieux) :
    ``[{"period": date, "value": Decimal}, ...]``."""
    include_vente = True
    include_ticket = True
    filters_vente: dict[str, Any] = {}
    filters_ticket: dict[str, Any] = {}

    if dimension_type == "canal":
        include_vente = dimension_value == "vente_directe"
        include_ticket = dimension_value == "pos"
    elif dimension_type in _SALES_SERIES_DIMENSION_FIELDS:
        field = _SALES_SERIES_DIMENSION_FIELDS[dimension_type]
        filters_vente = {field: dimension_value}
        filters_ticket = {field: dimension_value}
    else:
        return []

    monthly: dict[dt.date, Decimal] = defaultdict(Decimal)
    if include_vente:
        vente_rows = (
            AnFactVente.objects.filter(tenant=tenant, **filters_vente)
            .annotate(month=TruncMonth("dim_temps__date"))
            .values("month")
            .annotate(total=Sum("montant_ht_mga"))
        )
        for row in vente_rows:
            monthly[row["month"]] += row["total"] or Decimal(0)
    if include_ticket:
        ticket_rows = (
            AnFactTicketPos.objects.filter(tenant=tenant, **filters_ticket)
            .annotate(month=TruncMonth("dim_temps__date"))
            .values("month")
            .annotate(total=Sum("montant_ht_mga"))
        )
        for row in ticket_rows:
            monthly[row["month"]] += row["total"] or Decimal(0)

    if not monthly:
        return []

    first_month = min(monthly)
    last_month = max(monthly)
    all_months: list[dt.date] = []
    cursor = first_month
    while cursor <= last_month:
        all_months.append(cursor)
        cursor = (cursor.replace(day=1) + dt.timedelta(days=32)).replace(day=1)

    series = [{"period": month, "value": monthly.get(month, Decimal(0))} for month in all_months]
    return series[-periods:]


def get_partner_payment_behavior(tenant: Tenant) -> list[dict[str, Any]]:
    """Comportement de règlement observé PAR CLIENT (module `forecast`,
    FOR-9 : « dérive du comportement de règlement observé par client, pas
    un délai théorique unique »). **Simplification assumée et disclosée** :
    approxime le délai de règlement par l'écart entre la date moyenne des
    ventes et la date moyenne des encaissements du même tiers — un
    rapprochement facture-à-facture précis exigerait de porter le
    `matching_number` de lettrage (`apps.accounting`) jusque dans
    l'entrepôt, hors périmètre de ce lot ; cette moyenne reste un
    indicateur statistique réel et propre à chaque client, jamais un délai
    théorique unique appliqué à tous.

    Retourne ``[{"partner_id", "nom", "avg_delay_days"}, ...]`` — un client
    sans encaissement observé est absent (pas de délai inventé à 0)."""

    def _avg_ordinal_by_tiers(dates_by_tiers: dict[Any, list[dt.date]]) -> dict[Any, float]:
        return {
            tiers_id: sum(d.toordinal() for d in dates) / len(dates)
            for tiers_id, dates in dates_by_tiers.items()
            if dates
        }

    ventes_dates: dict[Any, list[dt.date]] = defaultdict(list)
    for row in AnFactVente.objects.filter(tenant=tenant, dim_tiers__isnull=False).values(
        "dim_tiers_id", "dim_temps__date"
    ):
        ventes_dates[row["dim_tiers_id"]].append(row["dim_temps__date"])

    encaissement_dates: dict[Any, list[dt.date]] = defaultdict(list)
    for row in AnFactEncaissement.objects.filter(tenant=tenant, dim_tiers__isnull=False).values(
        "dim_tiers_id", "dim_temps__date"
    ):
        encaissement_dates[row["dim_tiers_id"]].append(row["dim_temps__date"])

    ventes_avg = _avg_ordinal_by_tiers(ventes_dates)
    encaissements_avg = _avg_ordinal_by_tiers(encaissement_dates)

    results = []
    for dim_tiers_id, vente_avg in ventes_avg.items():
        encaissement_avg = encaissements_avg.get(dim_tiers_id)
        if encaissement_avg is None:
            continue
        tiers = AnDimTiers.objects.filter(id=dim_tiers_id).first()
        if tiers is None:
            continue
        results.append(
            {
                "partner_id": tiers.partner_id,
                "nom": tiers.nom,
                "avg_delay_days": max(round(encaissement_avg - vente_avg), 0),
            }
        )
    return results
