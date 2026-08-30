"""AI3 : auto-enregistrement d'une verification d'anomalie DETERMINISTE
du module `stocks` dans `core.services.anomaly_registry`, appele depuis
`apps.py::ready()` — meme patron que `ai_context_registration.
register_ai_context()`/`reports_registration.register_reports()` deja
etablis dans ce module.

**Adaptateur mince, pas une nouvelle regle metier** : `_check_negative_
stock` reutilise le perimetre "interne au sens valorisation" deja defini
par RG-STK-10/ST7 (`StkLocation.TYPE_INTERNE`/`TYPE_REBUT`, cf.
`services.moves._is_valuation_internal`, reimplemente ici a l'identique —
fonction privee, meme raisonnement "reuse si importable, sinon mirror
inline" que `services/budgets.py::_ratio_or_none`, A14) et
`StkNegativeStockException` (deja construit par ST7, lu ici via
`all_objects` pour recuperer `reason` — `has_negative_stock_exception`
public de ce meme module ne renvoie qu'un booleen, insuffisant pour la
description de l'anomalie) pour surfacer tout `StkQuant` interne
actuellement negatif :
- si AUCUNE exception active n'existe pour ce produit, c'est une anomalie
  `SEVERITY_HIGH` — RG-STK-10 interdit ce cas par defaut, sa presence
  signale un contournement de l'enforcement (`services.moves.validate_
  move`) ou une donnee historique anterieure a ST7 ;
- si une exception ACTIVE existe, c'est deja connu/autorise mais reste
  digne d'un suivi (`SEVERITY_MEDIUM`) : un stock negatif prolonge, meme
  autorise, merite d'etre revu (reappro, regularisation d'inventaire)."""

from __future__ import annotations

from apps.core.services.anomaly_registry import (
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    AnomalyCandidate,
    register_anomaly_check,
)
from apps.stocks.models import StkLocation, StkNegativeStockException, StkQuant


def _check_negative_stock(tenant_id: str) -> list[AnomalyCandidate]:
    candidates: list[AnomalyCandidate] = []
    quants = StkQuant.objects.filter(
        tenant_id=tenant_id,
        qty__lt=0,
        location__type__in=(StkLocation.TYPE_INTERNE, StkLocation.TYPE_REBUT),
    ).select_related("location")

    for quant in quants:
        exception = StkNegativeStockException.all_objects.filter(
            tenant_id=tenant_id, variant_id=quant.variant_id, is_active=True
        ).first()
        if exception is None:
            severity = SEVERITY_HIGH
            note = "aucune exception de stock negatif active pour ce produit"
        else:
            severity = SEVERITY_MEDIUM
            note = f"exception active (motif : {exception.reason or 'non renseigne'})"

        candidates.append(
            AnomalyCandidate(
                content_type_label="stocks.stkquant",
                object_id=str(quant.id),
                severity=severity,
                description=(
                    f"Stock negatif ({quant.qty}) sur l'emplacement interne "
                    f"{quant.location.code} pour le produit {quant.variant_id} — {note}."
                ),
            )
        )

    return candidates


def register_ai_anomaly_checks() -> None:
    register_anomaly_check(
        "stocks.negative_stock",
        module="stocks",
        label="Stock negatif sur un emplacement interne",
        function=_check_negative_stock,
    )
