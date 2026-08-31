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
