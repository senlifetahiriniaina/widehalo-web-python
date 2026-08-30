"""AI3 : auto-enregistrement d'une verification d'anomalie DETERMINISTE
du module `accounting` dans `core.services.anomaly_registry`, appele
depuis `apps.py::ready()` — meme patron que `ai_context_registration.
register_ai_context()`/`reports_registration.register_reports()` deja
etablis dans ce module.

**Adaptateur mince, pas une nouvelle regle metier** : `_check_budget_
variance` reutilise `_actual_amount` (deja construit par A14, cf.
`services/budgets.py::budget_variance_report`) pour recalculer l'ecart
reel/budgete de chaque `AccBudgetLine` d'un budget APPROUVE — jamais un
nouveau calcul d'ecart invente ici. Seuils de severite (20%/50%)
documentes comme des paliers raisonnables, pas des valeurs du CDC."""

from __future__ import annotations

from decimal import Decimal

from apps.accounting.models import AccBudget
from apps.accounting.services.budgets import _actual_amount
from apps.core.services.anomaly_registry import (
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    AnomalyCandidate,
    register_anomaly_check,
)

# Palier "moyenne" : un ecart de 20% ou plus entre reel et budgete sur un
# compte donne est deja significatif pour un suivi budgetaire mensuel.
_MEDIUM_VARIANCE_PCT = Decimal("20")
# Palier "haute" : un ecart de 50% ou plus signale un depassement/sous-
# consommation majeur, potentiellement bloquant pour la suite de
# l'exercice — seuil qui justifie l'evenement `ai.anomaly_detected`.
_HIGH_VARIANCE_PCT = Decimal("50")


def _check_budget_variance(tenant_id: str) -> list[AnomalyCandidate]:
    candidates: list[AnomalyCandidate] = []
    budgets = AccBudget.objects.filter(
        tenant_id=tenant_id, state=AccBudget.STATE_APPROVED
    ).prefetch_related("lines__account")

    for budget in budgets:
        for line in budget.lines.all():
            if line.budgeted_amount_mga == 0:
                # Meme garde que `_ratio_or_none` (A14) : un budget a
                # montant nul ne produit jamais un pourcentage d'ecart
                # fabrique.
                continue
            actual = _actual_amount(line)
            variance = actual - line.budgeted_amount_mga
            variance_pct = abs(variance / line.budgeted_amount_mga) * Decimal(100)
            if variance_pct < _MEDIUM_VARIANCE_PCT:
                continue
            severity = SEVERITY_HIGH if variance_pct >= _HIGH_VARIANCE_PCT else SEVERITY_MEDIUM
            candidates.append(
                AnomalyCandidate(
                    content_type_label="accounting.accbudgetline",
                    object_id=str(line.id),
                    severity=severity,
                    description=(
                        f"Ecart budgetaire de {variance_pct.quantize(Decimal('0.1'))}% sur le "
                        f"compte {line.account.code} ({line.account.name}) du budget "
                        f"{budget.reference} : budgete {line.budgeted_amount_mga} MGA, reel "
                        f"{actual} MGA (ecart {variance} MGA)."
                    ),
                )
            )
    return candidates


def register_ai_anomaly_checks() -> None:
    register_anomaly_check(
        "accounting.budget_variance",
        module="accounting",
        label="Ecart budgetaire significatif",
        function=_check_budget_variance,
    )
