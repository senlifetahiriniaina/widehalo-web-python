"""Contrat public de l'app `sales` — seule surface que les autres apps
metier ont le droit d'importer (cf. tests/architecture/test_module_boundaries.py).

S1/S2 du sous-sequencement (cf. plan) : tracabilite d'une reference de
devis ou de commande. `purchase`/`stocks`/`payroll`/`reporting`/`strategy`
pourront s'y brancher une fois les etapes ulterieures (S3-S7) livrees."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.db.models import Sum

from apps.sales.models import SalesForecast, SalesOrder, SalesOrderLine, SalesQuotation

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant


def get_quotation_reference(quotation_id: Any) -> str:
    quotation = SalesQuotation.objects.filter(id=quotation_id).first()
    return quotation.reference if quotation is not None else ""


def get_order_reference(order_id: Any) -> str:
    order = SalesOrder.objects.filter(id=order_id).first()
    return order.reference if order is not None else ""


def get_revenue_summary(*, date_from: Any, date_to: Any) -> Decimal:
    """Nouveau gap pour le module `simulation` (cahier §13.6) : passe-plat
    vers `services/reports.py::revenue_report` (SAL-CA), agrege en un seul
    montant total (le socle de simulation n'a pas besoin du detail par
    tiers/commercial/date, seulement du total de la periode de reference)."""
    from apps.sales.services.reports import revenue_report

    rows = revenue_report(date_from=date_from, date_to=date_to, group_by="date")
    return sum((row["total_mga"] for row in rows), Decimal(0))


def get_margin_summary(*, role_codes: set[str]) -> dict[str, Decimal] | None:
    """Nouveau gap pour le module `simulation` : passe-plat vers `services/
    reports.py::margin_report` (SAL-MARGE), agrege en `{"subtotal_mga",
    "cost_estimate_mga"}` — masquage par role deja applique en amont par
    `margin_report` (RG-SAL-5) : `cost_estimate_mga` peut etre absent des
    lignes si `role_codes` n'y donne pas droit, auquel cas cette fonction
    renvoie `None` plutot qu'un cout de revient invente a zero (le socle de
    simulation doit alors se rabattre sur `revenue_report` seul pour la
    marge — cf. `apps.simulation.services.baseline`)."""
    from apps.sales.services.reports import margin_report

    rows = margin_report(role_codes=role_codes)
    subtotal = sum((row["subtotal"] for row in rows), Decimal(0))
    if not rows or "cost_estimate_mga" not in rows[0]:
        return None
    cost_estimate = sum((row["cost_estimate_mga"] for row in rows), Decimal(0))
    return {"subtotal_mga": subtotal, "cost_estimate_mga": cost_estimate}


def get_delivered_qty_for_order(order_id: Any) -> Decimal | None:
    """Premier gap reel de lecture ajoute par `stocks` (ST6, RG-STK-6,
    "cohérence production/stock" — jambe "quantite livree au client") :
    somme de `SalesOrderLine.qty_delivered` (champ deja reel, cf.
    `apps.sales.models.SalesOrderLine`) sur TOUTES les lignes de la
    commande `order_id`.

    Retourne `None`, jamais une exception ni `Decimal(0)` deguise, si la
    commande n'existe pas — meme discipline "jamais de faux positif" que
    `mrp.services.public.get_order_produced_qty`/`get_supplier_score` : un
    appelant qui recoit `None` doit pouvoir distinguer "commande introuvable"
    de "commande existante mais rien livre" (`Decimal(0)`, une commande
    existante sans aucune ligne livree)."""
    if not SalesOrder.objects.filter(id=order_id).exists():
        return None
    total = SalesOrderLine.objects.filter(order_id=order_id).aggregate(total=Sum("qty_delivered"))[
        "total"
    ]
    return total if total is not None else Decimal(0)


def get_forecast_summary(
    tenant: Tenant, *, period_from: str, period_to: str
) -> list[dict[str, Any]]:
    """Nouveau gap ajoute pendant le chantier `strategy` (rapport business
    plan, section prevision) : mise a plat tabulaire des `SalesForecast`
    deja calcules (S6, `services.forecast.build_forecast`/
    `recompute_forecasts_for_period`) sur `[period_from, period_to]`
    inclus, AUCUN nouveau calcul de prevision ici — meme discipline que
    `services/reports.py::forecast_rows`, mais filtree EXPLICITEMENT sur
    `tenant` (appelee depuis un autre module, contrairement a `forecast_
    rows` qui compte sur le `TenantManager` deja scope au contexte HTTP
    courant)."""
    forecasts = SalesForecast.objects.filter(
        tenant=tenant, period__gte=period_from, period__lte=period_to, is_active=True
    ).order_by("period", "variant_id")
    return [
        {
            "period": forecast.period,
            "variant_id": str(forecast.variant_id),
            "qty_forecast": forecast.qty_forecast,
            "qty_actual": forecast.qty_actual,
            "confidence": forecast.confidence,
        }
        for forecast in forecasts
    ]


def count_orders_pending_confirmation() -> int:
    """Nombre de commandes de vente envoyees mais pas encore confirmees
    (`state=sent`) pour le tenant courant — deja tenant-scope par
    `SalesOrder.objects` (RLS), aucun parametre `tenant` necessaire.
    Utilise par le tableau de bord transversal (chantier UX6)."""
    return SalesOrder.objects.filter(state=SalesOrder.STATE_SENT).count()


def list_quotations_for_partner(partner_id: Any, *, limit: int = 20) -> list[dict[str, Any]]:
    """Gap PT6 du chantier "fiche partenaire a onglets par role" (cf.
    plan) : alimente l'onglet "Client" de la fiche partenaire avec les
    `SalesQuotation` de ce client — `partners` ne doit jamais importer
    `apps.sales.models` (regle de couplage n1).

    Retourne des dicts primitifs `{"id", "reference", "date", "state",
    "total"}`, jamais l'objet `SalesQuotation`, tries par date
    decroissante (devis le plus recent en premier). Liste vide, jamais
    d'exception, si aucun devis ne correspond a ce `partner_id`."""
    quotations = SalesQuotation.objects.filter(partner_id=partner_id).order_by("-date", "-id")[
        :limit
    ]
    return [
        {
            "id": quotation.id,
            "reference": quotation.reference,
            "date": quotation.date,
            "state": quotation.state,
            "total": quotation.amount_total_mga,
        }
        for quotation in quotations
    ]


def list_orders_for_partner(partner_id: Any, *, limit: int = 20) -> list[dict[str, Any]]:
    """Gap PT6 du chantier "fiche partenaire a onglets par role" (cf.
    plan) : alimente l'onglet "Client" de la fiche partenaire avec les
    `SalesOrder` de ce client — `partners` ne doit jamais importer
    `apps.sales.models` (regle de couplage n1). Homonyme de
    `purchase.services.public.list_orders_for_partner` (PT5) : chaque
    module a son propre `services/public.py`, aucune collision reelle.

    Retourne des dicts primitifs `{"id", "reference", "date", "state",
    "total"}`, jamais l'objet `SalesOrder`, tries par date decroissante
    (commande la plus recente en premier). Liste vide, jamais
    d'exception, si aucune commande ne correspond a ce `partner_id`."""
    orders = SalesOrder.objects.filter(partner_id=partner_id).order_by("-date", "-id")[:limit]
    return [
        {
            "id": order.id,
            "reference": order.reference,
            "date": order.date,
            "state": order.state,
            "total": order.amount_total_mga,
        }
        for order in orders
    ]
