"""Rafraîchissement de l'entrepôt en étoile (cahier Phase 2 §12) :
incrémental (jalons `AnWarehouseState.watermark_*`), verrouillable
(`AnWarehouseState.is_locked`), tracé (`AnRefreshRun`) et contrôlé par
réconciliation (`_check_reconciliation`).

**Limite disclosée (idempotence de type "upsert", pas de suppression)** :
une ligne source qui devient inéligible APRÈS un premier passage (ex. une
`SalesOrder` confirmée puis annulée) sort du filtre des fonctions `list_*_
for_warehouse` correspondantes — son fait déjà matérialisé n'est donc plus
retouché par un rafraîchissement incrémental ultérieur (`updated_at` de la
ligne source n'a pas nécessairement changé) et reste en base jusqu'à ce
qu'un opérateur purge manuellement `AnFactVente` pour ce tenant et relance
un rafraîchissement (qui repart alors de zéro, les jalons étant remis à
`None`) — aucun mécanisme de purge/rafraîchissement complet automatisé
n'est fourni dans ce lot, ni aucune planification récurrente Django-Q2
ailleurs dans le dépôt (cf. `apps.core.tasks`), même discipline que les
autres commandes `run_*` du projet."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import Max, Min, Sum
from django.utils import timezone

from apps.accounting.services.public import (
    list_move_lines_for_warehouse,
    list_payments_for_warehouse,
)
from apps.analytics.models import (
    AnDimArticle,
    AnDimTemps,
    AnDimTiers,
    AnFactEcriture,
    AnFactEncaissement,
    AnFactMouvementStock,
    AnFactTicketPos,
    AnFactVente,
    AnRefreshRun,
    AnWarehouseState,
)
from apps.catalog.services.public import list_variants_for_warehouse
from apps.core.tenant_context import activate_tenant
from apps.partners.services.public import list_partners_for_warehouse
from apps.pos.services.public import (
    list_order_lines_for_warehouse as list_pos_order_lines_for_warehouse,
)
from apps.sales.services.public import (
    get_untaxed_revenue_for_reconciliation,
)
from apps.sales.services.public import (
    list_order_lines_for_warehouse as list_sales_order_lines_for_warehouse,
)
from apps.stocks.services.public import list_moves_for_warehouse

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant

_MOIS_LIBELLES = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]  # fmt: skip
_JOURS_LIBELLES = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

_RECONCILIATION_TOLERANCE_MGA = Decimal("1")


def _ensure_dim_temps(
    tenant: Tenant, date: dt.date, cache: dict[dt.date, AnDimTemps]
) -> AnDimTemps:
    cached = cache.get(date)
    if cached is not None:
        return cached
    _, iso_week, iso_weekday = date.isocalendar()
    dim, _ = AnDimTemps.objects.update_or_create(
        tenant=tenant,
        date=date,
        defaults={
            "annee": date.year,
            "trimestre": (date.month - 1) // 3 + 1,
            "mois": date.month,
            "mois_libelle": _MOIS_LIBELLES[date.month - 1],
            "semaine_iso": iso_week,
            "jour_du_mois": date.day,
            "jour_semaine_iso": iso_weekday,
            "jour_semaine_libelle": _JOURS_LIBELLES[iso_weekday - 1],
            "est_weekend": iso_weekday in (6, 7),
            "exercice_fiscal": date.year,
        },
    )
    cache[date] = dim
    return dim


def _refresh_dim_tiers(tenant: Tenant) -> dict[Any, AnDimTiers]:
    by_partner_id: dict[Any, AnDimTiers] = {}
    for row in list_partners_for_warehouse(tenant):
        dim, _ = AnDimTiers.objects.update_or_create(
            tenant=tenant,
            partner_id=row["partner_id"],
            defaults={
                "code": row["code"],
                "nom": row["nom"],
                "roles": row["roles"],
                "is_placeholder": row["is_placeholder"],
            },
        )
        by_partner_id[row["partner_id"]] = dim
    return by_partner_id


def _refresh_dim_article(tenant: Tenant) -> dict[Any, AnDimArticle]:
    by_variant_id: dict[Any, AnDimArticle] = {}
    for row in list_variants_for_warehouse(tenant):
        dim, _ = AnDimArticle.objects.update_or_create(
            tenant=tenant,
            variant_id=row["variant_id"],
            defaults={
                "template_id": row["template_id"],
                "reference": row["reference"],
                "libelle": row["libelle"],
                "categorie_nom": row["categorie_nom"],
                "is_sellable": row["is_sellable"],
                "is_placeholder": row["is_placeholder"],
            },
        )
        by_variant_id[row["variant_id"]] = dim
    return by_variant_id


def _refresh_fact_vente(
    tenant: Tenant,
    state: AnWarehouseState,
    dim_temps_cache: dict[dt.date, AnDimTemps],
    dim_tiers: dict[Any, AnDimTiers],
    dim_article: dict[Any, AnDimArticle],
) -> int:
    rows = list_sales_order_lines_for_warehouse(
        tenant, updated_since=state.watermark_sales_orderline
    )
    latest_watermark = state.watermark_sales_orderline
    for row in rows:
        dim_temps = _ensure_dim_temps(tenant, row["order_date"], dim_temps_cache)
        AnFactVente.objects.update_or_create(
            tenant=tenant,
            source_line_id=row["line_id"],
            defaults={
                "dim_temps": dim_temps,
                "dim_tiers": dim_tiers.get(row["partner_id"]),
                "dim_article": dim_article.get(row["variant_id"]),
                "commercial_id": row["salesperson_id"],
                "order_reference": row["order_reference"],
                "order_state": row["order_state"],
                "canal": "vente_directe",
                "qty": row["qty"],
                "unit_price_mga": row["unit_price"],
                "discount_pct": row["discount_pct"],
                "montant_ht_mga": row["subtotal"],
                "cost_estimate_mga": row["cost_estimate_mga"],
                "margin_pct": row["margin_pct"],
            },
        )
        if latest_watermark is None or row["updated_at"] > latest_watermark:
            latest_watermark = row["updated_at"]
    state.watermark_sales_orderline = latest_watermark
    return len(rows)


def _refresh_fact_ticket_pos(
    tenant: Tenant,
    state: AnWarehouseState,
    dim_temps_cache: dict[dt.date, AnDimTemps],
    dim_tiers: dict[Any, AnDimTiers],
    dim_article: dict[Any, AnDimArticle],
) -> int:
    rows = list_pos_order_lines_for_warehouse(tenant, updated_since=state.watermark_pos_orderline)
    latest_watermark = state.watermark_pos_orderline
    for row in rows:
        order_date = row["order_created_at"].date()
        dim_temps = _ensure_dim_temps(tenant, order_date, dim_temps_cache)
        AnFactTicketPos.objects.update_or_create(
            tenant=tenant,
            source_line_id=row["line_id"],
            defaults={
                "dim_temps": dim_temps,
                "dim_tiers": dim_tiers.get(row["partner_id"]),
                "dim_article": dim_article.get(row["variant_id"]),
                "vendeur_id": row["cashier_id"],
                "point_vente_code": row["register_code"],
                "point_vente_nom": row["register_name"],
                "ticket_number": row["ticket_number"],
                "order_type": row["order_type"],
                "line_type": row["line_type"],
                "canal": "pos",
                "qty": row["qty"],
                "unit_price_mga": row["unit_price"],
                "discount_pct": row["discount_pct"],
                "montant_ht_mga": row["subtotal"],
                "montant_tva_mga": row["tax_amount"],
                "montant_ttc_mga": row["total"],
            },
        )
        if latest_watermark is None or row["updated_at"] > latest_watermark:
            latest_watermark = row["updated_at"]
    state.watermark_pos_orderline = latest_watermark
    return len(rows)


def _refresh_fact_encaissement(
    tenant: Tenant,
    state: AnWarehouseState,
    dim_temps_cache: dict[dt.date, AnDimTemps],
    dim_tiers: dict[Any, AnDimTiers],
) -> int:
    rows = list_payments_for_warehouse(tenant, updated_since=state.watermark_acc_payment)
    latest_watermark = state.watermark_acc_payment
    for row in rows:
        dim_temps = _ensure_dim_temps(tenant, row["date"], dim_temps_cache)
        AnFactEncaissement.objects.update_or_create(
            tenant=tenant,
            source_payment_id=row["payment_id"],
            defaults={
                "dim_temps": dim_temps,
                "dim_tiers": dim_tiers.get(row["partner_id"]),
                "reference": row["reference"],
                "direction": row["direction"],
                "method": row["method"],
                "montant_mga": row["amount"],
                "state": row["state"],
            },
        )
        if latest_watermark is None or row["updated_at"] > latest_watermark:
            latest_watermark = row["updated_at"]
    state.watermark_acc_payment = latest_watermark
    return len(rows)


def _refresh_fact_ecriture(
    tenant: Tenant,
    state: AnWarehouseState,
    dim_temps_cache: dict[dt.date, AnDimTemps],
    dim_tiers: dict[Any, AnDimTiers],
) -> int:
    rows = list_move_lines_for_warehouse(tenant, updated_since=state.watermark_acc_moveline)
    latest_watermark = state.watermark_acc_moveline
    for row in rows:
        dim_temps = _ensure_dim_temps(tenant, row["move_date"], dim_temps_cache)
        AnFactEcriture.objects.update_or_create(
            tenant=tenant,
            source_line_id=row["line_id"],
            defaults={
                "dim_temps": dim_temps,
                "dim_tiers": dim_tiers.get(row["partner_id"]),
                "compte_code": row["account_code"],
                "compte_libelle": row["account_name"],
                "compte_classe_pcg": row["account_class"],
                "move_reference": row["move_reference"],
                "move_type": row["move_type"],
                "debit_mga": row["debit"],
                "credit_mga": row["credit"],
                "solde_mga": row["debit"] - row["credit"],
            },
        )
        if latest_watermark is None or row["updated_at"] > latest_watermark:
            latest_watermark = row["updated_at"]
    state.watermark_acc_moveline = latest_watermark
    return len(rows)


def _refresh_fact_mouvement_stock(
    tenant: Tenant,
    state: AnWarehouseState,
    dim_temps_cache: dict[dt.date, AnDimTemps],
    dim_article: dict[Any, AnDimArticle],
) -> int:
    rows = list_moves_for_warehouse(tenant, updated_since=state.watermark_stk_move)
    latest_watermark = state.watermark_stk_move
    for row in rows:
        dim_temps = _ensure_dim_temps(tenant, row["date"], dim_temps_cache)
        AnFactMouvementStock.objects.update_or_create(
            tenant=tenant,
            source_move_id=row["move_id"],
            defaults={
                "dim_temps": dim_temps,
                "dim_article": dim_article.get(row["variant_id"]),
                "move_reference": row["reference"],
                "move_type": row["move_type"],
                "lot_name": row["lot_name"],
                "entrepot_origine_code": row["warehouse_from_code"],
                "emplacement_origine_code": row["location_from_code"],
                "entrepot_destination_code": row["warehouse_to_code"],
                "emplacement_destination_code": row["location_to_code"],
                "qty": row["qty"],
                "uom": row["uom"],
                "unit_cost_mga": row["unit_cost_mga"],
                "value_mga": row["value_mga"],
                "source_document": row["source_document"],
            },
        )
        if latest_watermark is None or row["updated_at"] > latest_watermark:
            latest_watermark = row["updated_at"]
    state.watermark_stk_move = latest_watermark
    return len(rows)


def _check_reconciliation(tenant: Tenant) -> tuple[bool | None, dict[str, Any]]:
    """Compare `sum(AnFactVente.montant_ht_mga)` au total HT calculé
    indépendamment par `sales.services.public.get_untaxed_revenue_for_
    reconciliation` sur la même fenêtre (même périmètre commandes actives
    non annulées, cf. docstring de cette fonction) — les deux calculs
    partent de la même source (`SalesOrder`/`SalesOrderLine`) par des
    chemins différents (somme ligne à ligne déjà matérialisée vs agrégat
    direct), donc un écart au-delà de l'arrondi signale une vraie
    incohérence de l'ETL, jamais une différence de périmètre attendue."""
    bounds = AnFactVente.objects.filter(tenant=tenant).aggregate(
        min_date=Min("dim_temps__date"), max_date=Max("dim_temps__date")
    )
    if bounds["min_date"] is None:
        return None, {}
    warehouse_total = AnFactVente.objects.filter(tenant=tenant).aggregate(
        total=Sum("montant_ht_mga")
    )["total"] or Decimal(0)
    reference_total = get_untaxed_revenue_for_reconciliation(
        date_from=bounds["min_date"], date_to=bounds["max_date"]
    )
    delta = warehouse_total - reference_total
    ok = abs(delta) <= _RECONCILIATION_TOLERANCE_MGA
    return ok, {
        "date_from": bounds["min_date"].isoformat(),
        "date_to": bounds["max_date"].isoformat(),
        "warehouse_total_mga": str(warehouse_total),
        "reference_total_mga": str(reference_total),
        "delta_mga": str(delta),
    }


def refresh_warehouse_for_tenant(
    tenant: Tenant, *, triggered_by: str = AnRefreshRun.TRIGGER_CRON
) -> AnRefreshRun:
    """Point d'entrée unique du rafraîchissement, pour UN tenant. Toute
    l'opération (verrou, upserts, jalons, journal) s'exécute dans le
    contexte tenant activé (`activate_tenant`, requis par la RLS pour
    toute écriture, même discipline que `run_sales_recurrences`)."""
    error: Exception | None = None
    with activate_tenant(tenant.id):
        run = AnRefreshRun.objects.create(
            tenant=tenant,
            started_at=timezone.now(),
            status=AnRefreshRun.STATUS_RUNNING,
            triggered_by=triggered_by,
        )
        state, _ = AnWarehouseState.objects.get_or_create(tenant=tenant)
        if state.is_locked:
            run.status = AnRefreshRun.STATUS_FAILED
            run.error_message = "Rafraîchissement déjà en cours (verrou actif)."
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "error_message", "finished_at"])
            return run

        state.is_locked = True
        state.locked_at = timezone.now()
        state.save(update_fields=["is_locked", "locked_at"])
        try:
            with transaction.atomic():
                dim_temps_cache: dict[dt.date, AnDimTemps] = {}
                dim_tiers = _refresh_dim_tiers(tenant)
                dim_article = _refresh_dim_article(tenant)
                rows_processed = 0
                rows_processed += _refresh_fact_vente(
                    tenant, state, dim_temps_cache, dim_tiers, dim_article
                )
                rows_processed += _refresh_fact_ticket_pos(
                    tenant, state, dim_temps_cache, dim_tiers, dim_article
                )
                rows_processed += _refresh_fact_encaissement(
                    tenant, state, dim_temps_cache, dim_tiers
                )
                rows_processed += _refresh_fact_ecriture(tenant, state, dim_temps_cache, dim_tiers)
                rows_processed += _refresh_fact_mouvement_stock(
                    tenant, state, dim_temps_cache, dim_article
                )
        except Exception as exc:  # noqa: BLE001 - trace l'echec en base plutot que de le laisser silencieux
            state.is_locked = False
            state.save(update_fields=["is_locked"])
            run.status = AnRefreshRun.STATUS_FAILED
            run.error_message = str(exc)
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "error_message", "finished_at"])
            error = exc
        else:
            state.is_locked = False
            state.last_successful_refresh_at = timezone.now()
            state.save(
                update_fields=[
                    "is_locked",
                    "last_successful_refresh_at",
                    "watermark_sales_orderline",
                    "watermark_pos_orderline",
                    "watermark_acc_payment",
                    "watermark_acc_moveline",
                    "watermark_stk_move",
                ]
            )
            reconciliation_ok, reconciliation_detail = _check_reconciliation(tenant)
            run.status = AnRefreshRun.STATUS_SUCCESS
            run.rows_processed = rows_processed
            run.reconciliation_ok = reconciliation_ok
            run.reconciliation_detail = reconciliation_detail
            run.finished_at = timezone.now()
            run.save(
                update_fields=[
                    "status",
                    "rows_processed",
                    "reconciliation_ok",
                    "reconciliation_detail",
                    "finished_at",
                ]
            )
    if error is not None:
        raise error
    return run


def enqueue_refresh(tenant: Tenant) -> str:
    """Enfile un rafraîchissement manuel via `apps.core.tasks.enqueue`
    (cahier §12, déclenchement à la demande depuis l'écran d'état de
    l'entrepôt) — même patron que `apps.simulation.services.baseline.
    refresh_baseline` : exécuté en SYNCHRONE dans les tests
    (`Q_CLUSTER["sync"] = True`)."""
    from apps.core.tasks import enqueue

    return enqueue(
        refresh_warehouse_for_tenant,
        tenant,
        triggered_by=AnRefreshRun.TRIGGER_MANUAL,
        task_name=f"analytics-warehouse-refresh-{tenant.id}",
    )
