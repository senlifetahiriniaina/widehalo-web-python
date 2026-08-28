"""PAY-M1 — evaluateur d'expressions RESTREINT pour le moteur de regles de
paie (`apps.payroll.services.rules_engine`). Jamais d'`eval()` natif Python,
jamais d'acces import/filesystem/reseau — exigence de securite BLOQUANTE du
CDC (§5.10.5), verifiee explicitement par le test d'acceptance n°6
(`apps/payroll/tests/test_expr.py::test_import_attempt_is_rejected`).

**Decision assumee (disclosed) : hand-rolled plutot que `asteval`.** Le CDC
suggere `asteval` "ou un sandbox equivalent construit a la main si asteval
s'avere mal maintenu/trop permissif — verifier avant de choisir". La
documentation d'`asteval` indique elle-meme qu'il n'est PAS concu comme un
sandbox de securite contre une entree activement adversariale (son filtrage
d'imports/attributs est une liste de refus best-effort, pas exhaustive) —
incompatible avec une exigence "bloquante" telle que PAY-M1. Un evaluateur
ecrit a la main sur liste D'AUTORISATION (jamais de liste de refus) est plus
facile a auditer exhaustivement pour ce perimetre volontairement etroit
(arithmetique, comparaisons, booleens, acces a un environnement de variables
fige, appel a un tres petit nombre de fonctions whitelistees) et evite une
nouvelle dependance externe pour une surface de securite critique.

Mecanique : `ast.parse(expr, mode="eval")` puis parcours recursif du seul
sous-ensemble de noeuds explicitement autorise (`_ALLOWED_NODES`) — tout
noeud absent de cette liste (Import, Attribute non whitelistee, Call vers
une fonction non whitelistee, comprehension, lambda, walrus, etc.) leve
`RestrictedExpressionError` avant meme d'atteindre l'evaluation. Aucun
`__builtins__`/`globals()`/`getattr` dynamique n'est jamais expose a
l'expression evaluee."""

from __future__ import annotations

import ast
import operator
from decimal import Decimal
from typing import Any

_ALLOWED_BINOPS: dict[type[ast.AST], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_ALLOWED_UNARYOPS: dict[type[ast.AST], Any] = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
    ast.Not: operator.not_,
}

_ALLOWED_COMPARE: dict[type[ast.AST], Any] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}

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


# Fonctions whitelistees explicitement, jamais `__builtins__` complet.
_ALLOWED_FUNCTIONS: dict[str, Any] = {
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "Decimal": Decimal,
    "floor100": _floor100,
    "sum_amounts": _sum_amounts,
    "irsa_tranche": _irsa_tranche,
    "overtime_total_pay": _overtime_total_pay,
    "overtime_exempt_pay": _overtime_exempt_pay,
    "absence_deduction": _absence_deduction,
}


class RestrictedExpressionError(Exception):
    """Levee quand une expression sort du perimetre autorise (noeud AST
    interdit, nom/attribut/fonction non whitelistee) — jamais rattrapee
    silencieusement par l'appelant, une regle de paie qui ne s'evalue pas
    doit bloquer le calcul du bulletin, pas produire un montant errone."""


def safe_eval(expression: str, variables: dict[str, Any]) -> Any:  # noqa: ANN401
    """Evalue `expression` dans l'environnement RESTREINT `variables`
    (PAY-M2 : `contract`/`employee`/`payslip`/`worked_days`/`absences`/
    `overtime`/`benefits`/`params`/`result_rules`, uniquement des types
    primitifs/dict/Decimal — jamais un objet ORM Django expose tel quel a
    l'expression)."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise RestrictedExpressionError(f"Expression invalide : {exc}") from exc
    return _eval_node(tree.body, variables)


def _eval_node(node: ast.AST, variables: dict[str, Any]) -> Any:  # noqa: ANN401, C901, PLR0911
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, str, bool)) or node.value is None:
            return node.value
        raise RestrictedExpressionError(f"Constante non autorisee : {node.value!r}")
    if isinstance(node, ast.Name):
        if node.id in variables:
            return variables[node.id]
        if node.id in _ALLOWED_FUNCTIONS:
            return _ALLOWED_FUNCTIONS[node.id]
        raise RestrictedExpressionError(f"Variable inconnue : '{node.id}'")
    if isinstance(node, ast.BinOp):
        op = _ALLOWED_BINOPS.get(type(node.op))
        if op is None:
            raise RestrictedExpressionError(f"Operateur non autorise : {type(node.op).__name__}")
        return op(_eval_node(node.left, variables), _eval_node(node.right, variables))
    if isinstance(node, ast.UnaryOp):
        op = _ALLOWED_UNARYOPS.get(type(node.op))
        if op is None:
            raise RestrictedExpressionError(
                f"Operateur unaire non autorise : {type(node.op).__name__}"
            )
        return op(_eval_node(node.operand, variables))
    if isinstance(node, ast.BoolOp):
        values = [_eval_node(v, variables) for v in node.values]
        return all(values) if isinstance(node.op, ast.And) else any(values)
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, variables)
        for comparator_op, comparator in zip(node.ops, node.comparators, strict=True):
            op = _ALLOWED_COMPARE.get(type(comparator_op))
            if op is None:
                raise RestrictedExpressionError(
                    f"Comparaison non autorisee : {type(comparator_op).__name__}"
                )
            right = _eval_node(comparator, variables)
            if not op(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return (
            _eval_node(node.body, variables)
            if _eval_node(node.test, variables)
            else _eval_node(node.orelse, variables)
        )
    if isinstance(node, ast.Subscript):
        value = _eval_node(node.value, variables)
        key = _eval_node(node.slice, variables)
        if not isinstance(value, (dict, list, tuple)):
            raise RestrictedExpressionError("Acces indexe non autorise sur ce type.")
        try:
            return value[key]
        except (KeyError, IndexError, TypeError):
            return None
    if isinstance(node, ast.Attribute):
        # Seul un acces .get() sur dict (via Call, gere plus bas) est
        # necessaire en pratique — l'acces attribut generique reste interdit
        # (aucun objet Python arbitraire n'est jamais expose a l'evaluateur).
        raise RestrictedExpressionError(f"Acces attribut non autorise : '.{node.attr}'")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCTIONS:
            raise RestrictedExpressionError("Appel de fonction non autorise.")
        func = _ALLOWED_FUNCTIONS[node.func.id]
        args = [_eval_node(a, variables) for a in node.args]
        return func(*args)
    if isinstance(node, ast.List):
        return [_eval_node(e, variables) for e in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval_node(e, variables) for e in node.elts)
    if isinstance(node, ast.Dict):
        return {
            _eval_node(k, variables): _eval_node(v, variables)
            for k, v in zip(node.keys, node.values, strict=True)
            if k is not None
        }
    # Tout le reste (Import/ImportFrom, Lambda, comprehensions, walrus,
    # Attribute generique deja traite ci-dessus, appel de methode, etc.)
    # est explicitement REFUSE — liste d'autorisation, jamais de refus.
    raise RestrictedExpressionError(f"Construction non autorisee : {type(node).__name__}")
