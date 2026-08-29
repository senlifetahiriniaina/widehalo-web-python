"""PAY-M1 — fonctions whitelistees METIER du moteur de regles de paie
(`apps.payroll.services.rules_engine`), evaluees par le moteur GENERIQUE
desormais extrait dans `apps.core.services.expr` (AUTO1, chantier Studio de
workflow visuel — meme discipline que l'extraction de
`apps.core.services.object_remap` au chantier backup/restore : un
mecanisme de securite ne doit jamais exister en deux copies potentiellement
divergentes).

**Refactor SANS changement de comportement** : `safe_eval(expression,
variables)` ci-dessous a exactement la meme signature et le meme
comportement qu'avant l'extraction — il delegue au `safe_eval` generique de
`core.services.expr`, en lui passant `PAYROLL_FUNCTIONS` (les fonctions
metier ci-dessous, ex. `irsa_tranche`) EN PLUS de `GENERIC_FUNCTIONS`
(`min`/`max`/`abs`/`round`/`Decimal`) que le moteur generique fournit
toujours. Verifie par `apps/payroll/tests/test_expr.py` (regression, y
compris les 10 variantes d'evasion §5.10.10 n°6) — aucun changement
attendu de comportement, uniquement de l'implementation."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.core.services.expr import RestrictedExpressionError
from apps.core.services.expr import safe_eval as _core_safe_eval

__all__ = [
    "DEFAULT_OVERTIME_MULTIPLIERS",
    "PAYROLL_FUNCTIONS",
    "RestrictedExpressionError",
    "safe_eval",
]

# Multiplicateurs par defaut des categories d'heures supplementaires — le
# CDC (§5.10.6, RG-PAY-1) renvoie a `PrsWorkCalendar.overtime_rules`
# (JSONField cote `presence`), mais ce champ n'est PAS expose par
# `apps.presence.services.public` (couplage n1 : jamais d'acces direct au
# modele) — table par defaut assumee ici, disclosed. Une vraie
# parametrisation par tenant deviendrait naturellement un nouveau
# `RegulatoryParameter` (`payroll.overtime_multipliers`) si le besoin se
# confirme, hors perimetre de ce chantier.
DEFAULT_OVERTIME_MULTIPLIERS: dict[str, Decimal] = {
    "h_sup_30": Decimal("1.30"),
    "h_sup_50": Decimal("1.50"),
    "nuit": Decimal("1.30"),
    "dimanche": Decimal("1.40"),
    "ferie": Decimal("2.00"),
}


def _floor100(value: Any) -> Decimal:  # noqa: ANN401
    """RG-PAY-1 : base IRSA arrondie a la centaine INFERIEURE."""
    amount = Decimal(str(value))
    return (amount // 100) * 100


def _sum_amounts(items: Any, key: str) -> Decimal:  # noqa: ANN401
    """Somme `Decimal(item[key])` sur une liste de dict — les avantages
    contractuels (`benefits`, PAY-M2) notamment."""
    return sum((Decimal(str(item[key])) for item in items), Decimal(0))


def _irsa_tranche(base: Any, brackets: Any, minimum: Any) -> Decimal:  # noqa: ANN401
    """Bareme IRSA 6 tranches PROGRESSIF (§5.10.3) + minimum de perception
    (floor) — SANS la reduction pour personne a charge, appliquee comme une
    ligne de regle separee (§5.10.5, disclosed dans
    `apps.payroll.services.params.compute_irsa_bracket_tax`, meme formule
    exacte, verifiee identique par les tests d'acceptance)."""
    base_decimal: Decimal = Decimal(str(base))
    minimum_decimal: Decimal = Decimal(str(minimum))
    tax = Decimal(0)
    for bracket in brackets:
        lo = Decimal(str(bracket["min"]))
        hi_raw = bracket["max"]
        hi = Decimal(str(hi_raw)) if hi_raw is not None else None
        if base_decimal < lo:
            continue
        upper = hi if hi is not None else base_decimal
        portion = min(base_decimal, upper) - lo + Decimal(1)
        if portion <= 0:
            continue
        tax += portion * Decimal(str(bracket["rate"]))
    if base_decimal <= 0:
        return Decimal(0)
    return max(tax, minimum_decimal)


def _overtime_total_pay(hourly_rate: Any, overtime_hours: Any) -> Decimal:  # noqa: ANN401
    """Total paye des heures supplementaires, toutes categories confondues,
    majorees selon `DEFAULT_OVERTIME_MULTIPLIERS` (categorie inconnue -> pas
    de majoration, multiplicateur 1)."""
    rate = Decimal(str(hourly_rate))
    total = Decimal(0)
    for category, hours in overtime_hours.items():
        multiplier = DEFAULT_OVERTIME_MULTIPLIERS.get(category, Decimal(1))
        total += Decimal(str(hours)) * rate * multiplier
    return total


def _overtime_exempt_pay(hourly_rate: Any, overtime_hours: Any, exempt_hours: Any) -> Decimal:  # noqa: ANN401
    """RG-PAY (§5.10.3) : les `exempt_hours` PREMIERES heures sup sont
    exonerees d'IRSA (jamais de cotisations sociales — non precise par le
    CDC, disclosed que seule l'exoneration IRSA est modelisee). Simplification
    assumee : la portion exoneree est valorisee au taux MOYEN de l'ensemble
    des heures sup du bulletin (toutes categories melangees), pas categorie
    par categorie dans un ordre impose que le CDC ne precise pas."""
    total_hours = sum((Decimal(str(h)) for h in overtime_hours.values()), Decimal(0))
    if total_hours <= 0:
        return Decimal(0)
    total_pay = _overtime_total_pay(hourly_rate, overtime_hours)
    average_rate = total_pay / total_hours
    exempt = min(total_hours, Decimal(str(exempt_hours)))
    return average_rate * exempt


def _absence_deduction(daily_rate: Any, absences: Any) -> Decimal:  # noqa: ANN401
    """RG-PAY-4 : retenue proportionnelle au taux de remuneration NON
    couvert par `pay_rate_pct` de chaque type d'absence (ex. 0% pour une
    absence injustifiee = retenue integrale du jour, 100% pour un conge
    paye = aucune retenue)."""
    rate = Decimal(str(daily_rate))
    total = Decimal(0)
    for absence in absences:
        days = Decimal(str(absence["days"]))
        pay_rate_pct = Decimal(str(absence["pay_rate_pct"]))
        unpaid_fraction = (Decimal(100) - pay_rate_pct) / Decimal(100)
        total += days * rate * unpaid_fraction
    return total


# Fonctions whitelistees METIER, en plus de `core.services.expr.
# GENERIC_FUNCTIONS` — jamais `__builtins__` complet.
PAYROLL_FUNCTIONS: dict[str, Any] = {
    "floor100": _floor100,
    "sum_amounts": _sum_amounts,
    "irsa_tranche": _irsa_tranche,
    "overtime_total_pay": _overtime_total_pay,
    "overtime_exempt_pay": _overtime_exempt_pay,
    "absence_deduction": _absence_deduction,
}


def safe_eval(expression: str, variables: dict[str, Any]) -> Any:  # noqa: ANN401
    """Evalue `expression` dans l'environnement RESTREINT `variables`
    (PAY-M2 : `contract`/`employee`/`payslip`/`worked_days`/`absences`/
    `overtime`/`benefits`/`params`/`result_rules`, uniquement des types
    primitifs/dict/Decimal — jamais un objet ORM Django expose tel quel a
    l'expression). Delegue au moteur generique `core.services.expr.
    safe_eval`, complete de `PAYROLL_FUNCTIONS` (signature/comportement
    inchanges par rapport a avant l'extraction AUTO1)."""
    return _core_safe_eval(expression, variables, functions=PAYROLL_FUNCTIONS)
