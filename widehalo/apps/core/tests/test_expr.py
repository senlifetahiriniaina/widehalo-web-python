"""AUTO1 (chantier Studio de workflow visuel) — evaluateur d'expressions
restreint partage, extrait de `apps.payroll.services.expr` (PAY-M1). Meme
contrat de securite que le test d'acceptance payroll §5.10.10 n°6
(`apps/payroll/tests/test_expr.py`), verifie ici directement au niveau
`core` puisque c'est desormais le point d'implementation unique."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from apps.core.services.expr import RestrictedExpressionError, safe_eval


def test_basic_arithmetic() -> None:
    assert safe_eval("1 + 2 * 3", {}) == 7


def test_variable_lookup() -> None:
    assert safe_eval("base * rate", {"base": Decimal(1000), "rate": Decimal("0.1")}) == Decimal(
        "100.0"
    )


def test_generic_functions_available_by_default() -> None:
    assert safe_eval("min(a, b)", {"a": Decimal(5), "b": Decimal(3)}) == Decimal(3)
    assert safe_eval("max(a, b)", {"a": Decimal(5), "b": Decimal(3)}) == Decimal(5)
    assert safe_eval("abs(a)", {"a": -3}) == 3
    assert safe_eval("round(a)", {"a": 3.6}) == 4
    assert safe_eval("Decimal('1.5')", {}) == Decimal("1.5")


def test_extra_functions_are_additive_not_replacing_generic() -> None:
    """`functions=` complete `GENERIC_FUNCTIONS`, ne les remplace jamais —
    une condition de flux `automation` qui passe une fonction dediee garde
    quand meme `min`/`max`/`abs`/`round`/`Decimal`."""

    def double(x: Any) -> Any:  # noqa: ANN401
        return x * 2

    assert safe_eval("double(min(a, b))", {"a": 5, "b": 3}, functions={"double": double}) == 6


def test_dict_and_subscript_access() -> None:
    assert safe_eval("payload['amount']", {"payload": {"amount": 42}}) == 42
    assert safe_eval("payload['missing']", {"payload": {}}) is None


def test_boolean_and_comparison() -> None:
    assert safe_eval("a > 10 and b < 5", {"a": 20, "b": 1}) is True
    assert safe_eval("a > 10 and b < 5", {"a": 1, "b": 1}) is False


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
    with pytest.raises((RestrictedExpressionError,)):
        safe_eval(expression, {})


def test_unknown_variable_rejected() -> None:
    with pytest.raises(RestrictedExpressionError):
        safe_eval("secret_key", {})


def test_unknown_function_rejected() -> None:
    with pytest.raises(RestrictedExpressionError):
        safe_eval("os.system('x')", {"os": object()})
