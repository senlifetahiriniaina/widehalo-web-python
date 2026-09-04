"""PAY-M1 — test d'acceptance §5.10.10 n°6 : une expression de regle
tentant d'importer un module est rejetee par l'evaluateur restreint."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.payroll.services.expr import RestrictedExpressionError, safe_eval


def test_basic_arithmetic() -> None:
    assert safe_eval("1 + 2 * 3", {}) == 7


def test_variable_lookup() -> None:
    assert safe_eval("base * rate", {"base": Decimal(1000), "rate": Decimal("0.1")}) == Decimal(
        "100.0"
    )


def test_min_max_whitelisted() -> None:
    assert safe_eval("min(a, b)", {"a": Decimal(5), "b": Decimal(3)}) == Decimal(3)


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo pwned')",
        "import os",
        "os.system('echo pwned')",
        "(1).__class__.__bases__",
        "().__class__.__mro__[1].__subclasses__()",
        "open('/etc/passwd').read()",
        "eval('1+1')",
        "exec('pass')",
        "lambda: 1",
        "[x for x in range(10)]",
    ],
)
def test_import_attempt_is_rejected(expression: str) -> None:
    """PAY-M1 / test d'acceptance §5.10.10 n°6 — chaque variante ci-dessus
    doit lever `RestrictedExpressionError` (SyntaxError pour `import os`,
    capturee et re-levee comme telle) AVANT toute execution."""
    with pytest.raises((RestrictedExpressionError,)):
        safe_eval(expression, {})


def test_unknown_variable_rejected() -> None:
    with pytest.raises(RestrictedExpressionError):
        safe_eval("secret_key", {})


def test_unknown_function_rejected() -> None:
    with pytest.raises(RestrictedExpressionError):
        safe_eval("os.system('x')", {"os": object()})


class TestOvertimeMultipliers:
    """Bloc E, E1 (PAY-1) : `overtime_total_pay`/`overtime_exempt_pay` ne
    lisent plus aucun bareme en dur — les multiplicateurs sont TOUJOURS
    fournis explicitement par l'appelant (`params['overtime_multipliers']`,
    resolu depuis le `RegulatoryParameter` `payroll.overtime_multipliers`
    par `apps.payroll.services.params.resolve_params`), jamais un defaut
    module-level."""

    def test_overtime_total_pay_applies_provided_multipliers(self) -> None:
        result = safe_eval(
            "overtime_total_pay(rate, overtime, multipliers)",
            {
                "rate": Decimal("1000"),
                "overtime": {"h_sup_30": Decimal("2"), "h_sup_50": Decimal("1")},
                "multipliers": {"h_sup_30": Decimal("1.30"), "h_sup_50": Decimal("1.50")},
            },
        )
        # 2h * 1000 * 1.30 + 1h * 1000 * 1.50 = 2600 + 1500 = 4100.
        assert result == Decimal("4100")

    def test_overtime_total_pay_reflects_a_different_multiplier_table(self) -> None:
        """Preuve directe qu'aucune table n'est figee dans le code : deux
        appels avec deux dicts `multipliers` differents pour la MEME
        categorie produisent des resultats differents."""
        variables = {
            "rate": Decimal("1000"),
            "overtime": {"h_sup_30": Decimal("2")},
        }
        low = safe_eval(
            "overtime_total_pay(rate, overtime, multipliers)",
            {**variables, "multipliers": {"h_sup_30": Decimal("1.10")}},
        )
        high = safe_eval(
            "overtime_total_pay(rate, overtime, multipliers)",
            {**variables, "multipliers": {"h_sup_30": Decimal("2.00")}},
        )
        assert low == Decimal("2200")
        assert high == Decimal("4000")
        assert low != high

    def test_overtime_total_pay_unknown_category_defaults_to_multiplier_one(self) -> None:
        result = safe_eval(
            "overtime_total_pay(rate, overtime, multipliers)",
            {
                "rate": Decimal("1000"),
                "overtime": {"categorie_inconnue": Decimal("3")},
                "multipliers": {"h_sup_30": Decimal("1.30")},
            },
        )
        assert result == Decimal("3000")

    def test_overtime_exempt_pay_uses_provided_multipliers_for_average_rate(self) -> None:
        result = safe_eval(
            "overtime_exempt_pay(rate, overtime, exempt_hours, multipliers)",
            {
                "rate": Decimal("1000"),
                "overtime": {"h_sup_50": Decimal("4")},
                "exempt_hours": Decimal("2"),
                "multipliers": {"h_sup_50": Decimal("1.50")},
            },
        )
        # Taux moyen = 1000 * 1.50 = 1500 ; 2h exonerees x 1500 = 3000.
        assert result == Decimal("3000")
