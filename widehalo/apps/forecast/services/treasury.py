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


def _weighted_average_delay(behavior: list[dict[str, Any]]) -> int:
    """Delai moyen PONDERE par le poids de chaque client.

    La moyenne non ponderee donnait le meme poids a un client d'une
    facture et a un client de cinq cents. Le poids retenu est le nombre de
    ventes observees (`sales_count` quand l'entrepot le fournit), a defaut
    un poids egal — auquel cas on retombe sur l'ancienne moyenne, ce qui
    est le comportement correct : sans information de poids, ponderer
    reviendrait a en inventer une."""
    if not behavior:
        return _DEFAULT_DELAY_DAYS
    weights = [float(row.get("sales_count") or 1) for row in behavior]
    total_weight = sum(weights)
    if not total_weight:
        return _DEFAULT_DELAY_DAYS
    return round(
        sum(float(row["avg_delay_days"]) * w for row, w in zip(behavior, weights, strict=True))
        / total_weight
    )


def project_twelve_month_cash_inflows(tenant: Tenant) -> dict[str, Any]:
    """Projette les encaissements des 12 prochains mois a partir des
    previsions de ventes, decalees du delai de reglement OBSERVE.

    **FOR-9, et ce que le blocage etait reellement (L9).** La version
    precedente ecrasait en une MOYENNE NON PONDEREE les delais par client
    que `get_partner_payment_behavior` fournit deja individuellement :
    un client avec une facture pesait autant qu'un client avec cinq cents.
    Mais le blocage n'etait pas la formule — c'etait la DIMENSION LUE. Les
    previsions consommees etaient filtrees sur `DIMENSION_CANAL`, un
    agregat qui ne porte aucun client : il n'y avait rien a quoi rattacher
    un delai individuel.

    Deux regimes, donc, et le resultat dit lequel s'applique :

    - **des previsions PAR CLIENT existent** (`DIMENSION_CLIENT`) : chacune
      est decalee du delai propre a SON client. C'est le critere tenu au
      sens strict ;
    - **sinon**, repli sur la serie « canal » avec un delai unique — mais
      PONDERE par le poids reel de chaque client dans les encaissements
      observes, jamais une moyenne plate. Un repli reste un repli : il est
      nomme dans `assumption_basis`, pas dissimule.

    Les deux sources ne sont jamais melangees : additionner une prevision
    par client et une prevision par canal compterait deux fois le meme
    chiffre d'affaires."""
    behavior = get_partner_payment_behavior(tenant)
    delay_by_partner = {str(row["partner_id"]): row["avg_delay_days"] for row in behavior}
    weighted_delay = _weighted_average_delay(behavior)

    client_forecasts = list(
        ForSeriesForecast.objects.filter(
            tenant=tenant, dimension_type=ForSeriesForecast.DIMENSION_CLIENT
        ).order_by("period")
    )
    if client_forecasts:
        basis = "par_client"
        rows = [
            (forecast, delay_by_partner.get(forecast.dimension_value, weighted_delay))
            for forecast in client_forecasts
        ]
        # Delai annonce : celui reellement applique en moyenne, pondere par
        # les montants prevus — sans quoi l'hypothese affichee ne
        # correspondrait a aucun des calculs faits.
        total = sum((f.final_value for f, _ in rows), Decimal(0))
        avg_delay_days = (
            round(sum(float(f.final_value) * d for f, d in rows) / float(total))
            if total
            else weighted_delay
        )
    else:
        basis = "canal_pondere"
        avg_delay_days = weighted_delay
        rows = [
            (forecast, weighted_delay)
            for forecast in ForSeriesForecast.objects.filter(
                tenant=tenant, dimension_type=ForSeriesForecast.DIMENSION_CANAL
            ).order_by("period")
        ]

    monthly_inflows: dict[dt.date, Decimal] = {}
    for forecast, delay_days in rows:
        inflow_month = (forecast.period + dt.timedelta(days=delay_days)).replace(day=1)
        monthly_inflows[inflow_month] = (
            monthly_inflows.get(inflow_month, Decimal(0)) + forecast.final_value
        )

    return {
        "assumption_avg_delay_days": avg_delay_days,
        # FOR-9 : dire SUR QUOI repose la projection. « 47 jours » ne veut
        # pas dire la meme chose selon qu'il s'agit du delai propre a
        # chaque client ou d'une moyenne appliquee a tous.
        "assumption_basis": basis,
        "assumption_note": (
            "Décaissements connus/récurrents non projetés dans cette version "
            "(non encore alimentés dans l'entrepôt analytique)."
        ),
        "monthly_inflows": [
            {"period": period, "value": value} for period, value in sorted(monthly_inflows.items())
        ],
    }
