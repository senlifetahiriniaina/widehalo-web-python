"""Trésorerie à douze mois (cahier §13.2, écran "Trésorerie à douze mois" :
« prolonge à douze mois la projection à treize semaines de la Phase 1
[Simulation, §13.6] »). **Limite assumée et disclosée** : projette
uniquement les ENCAISSEMENTS (ventes prévues, décalées du délai de
règlement observé par client, FOR-9) — l'entrepôt analytique
(`apps.analytics.AnFactEncaissement`, cf. `apps.analytics.services.
fact_specs`) ne capture aujourd'hui que les paiements `direction=inbound`,
aucun décaissement récurrent connu (achats/paie) n'y est encore
matérialisé ; les "décaissements connus/récurrents" du cahier restent donc
hors périmètre de cette première version, à combler quand `purchase`/
`payroll` alimenteront l'entrepôt. Les hypothèses retenues (délai moyen
par client, périodes couvertes) sont toujours renvoyées explicitement
(cahier : "hypothèses affichées")."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from apps.analytics.services.public import get_partner_payment_behavior
from apps.forecast.models import ForSeriesForecast

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant

_DEFAULT_DELAY_DAYS = 30


def project_twelve_month_cash_inflows(tenant: Tenant) -> dict[str, Any]:
    """Projette les encaissements des 12 prochains mois à partir des
    prévisions de ventes publiées/calculées (`ForSeriesForecast` dont
    `dimension_type="canal"`), décalées d'un délai moyen. Sans
    ventilation par client dans la série "canal" (agrégat global), le
    délai retenu est la MOYENNE des délais observés tous clients confondus
    — hypothèse affichée explicitement (cahier), pas un délai unique
    caché."""
    behavior = get_partner_payment_behavior(tenant)
    avg_delay_days = (
        round(sum(b["avg_delay_days"] for b in behavior) / len(behavior))
        if behavior
        else _DEFAULT_DELAY_DAYS
    )

    sales_forecasts = ForSeriesForecast.objects.filter(
        tenant=tenant, dimension_type=ForSeriesForecast.DIMENSION_CANAL
    ).order_by("period")

    monthly_inflows: dict[dt.date, Decimal] = {}
    for forecast in sales_forecasts:
        inflow_period = forecast.period + dt.timedelta(days=avg_delay_days)
        inflow_month = inflow_period.replace(day=1)
        monthly_inflows[inflow_month] = monthly_inflows.get(inflow_month, Decimal(0)) + forecast.final_value

    return {
        "assumption_avg_delay_days": avg_delay_days,
        "assumption_note": (
            "Décaissements connus/récurrents non projetés dans cette version "
            "(non encore alimentés dans l'entrepôt analytique)."
        ),
        "monthly_inflows": [
            {"period": period, "value": value} for period, value in sorted(monthly_inflows.items())
        ],
    }
