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
