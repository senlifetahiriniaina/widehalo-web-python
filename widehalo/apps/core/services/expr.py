"""Evaluateur d'expressions RESTREINT partage (AUTO1, chantier Studio de
workflow visuel) — EXTRAIT de `apps.payroll.services.expr` (construit au
chantier `payroll`, PAY-M1) vers `core` pour eviter la duplication d'un
mecanisme de securite, meme discipline deja appliquee par
`apps.core.services.object_remap` (chantier backup/restore) : un
algorithme de securite ne doit jamais exister en deux copies potentiellement
divergentes.

Jamais d'`eval()` natif Python, jamais d'acces import/filesystem/reseau —
liste D'AUTORISATION exhaustive (jamais une liste de refus), verifiee par
`apps/payroll/tests/test_expr.py` (regression, 10 variantes d'evasion) et
`apps/core/tests/test_expr.py` (le meme contrat, teste directement ici).

**Refactor SANS changement de comportement** : `payroll.services.expr`
importe desormais `safe_eval`/`RestrictedExpressionError` d'ici et lui
fournit ses fonctions whitelistees METIER (`irsa_tranche`, etc.) via le
parametre `functions` — ce module ne connait, lui, que les fonctions
GENERIQUES (`min`/`max`/`abs`/`round`/`Decimal`), suffisantes pour un
consommateur generique comme une condition de flux `automation.AutoStep`
(RG le decideur au moment de l'implementation : jamais de fonction
specifique a un module metier codee en dur ici).

Mecanique inchangee : `ast.parse(expr, mode="eval")` puis parcours
recursif du seul sous-ensemble de noeuds explicitement autorise — tout
noeud absent (Import, Attribute non whitelistee, Call vers une fonction
non whitelistee, comprehension, lambda, walrus, etc.) leve
`RestrictedExpressionError` avant meme d'atteindre l'evaluation. Aucun
`__builtins__`/`globals()`/`getattr` dynamique n'est jamais expose."""

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

# Fonctions whitelistees GENERIQUES, communes a tout consommateur de cet
# evaluateur (payroll y ajoute ses propres fonctions metier, cf.
# `apps.payroll.services.expr.PAYROLL_FUNCTIONS`) — jamais `__builtins__`
# complet.
GENERIC_FUNCTIONS: dict[str, Any] = {
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "Decimal": Decimal,
}


class RestrictedExpressionError(Exception):
    """Levee quand une expression sort du perimetre autorise (noeud AST
    interdit, nom/attribut/fonction non whitelistee) — jamais rattrapee
    silencieusement par l'appelant : une expression qui ne s'evalue pas
    doit bloquer l'appelant (calcul de bulletin, condition de flux), pas
    produire un resultat errone."""


def safe_eval(
    expression: str, variables: dict[str, Any], *, functions: dict[str, Any] | None = None
) -> Any:  # noqa: ANN401
    """Evalue `expression` dans l'environnement RESTREINT `variables`,
    avec pour seules fonctions appelables `GENERIC_FUNCTIONS` completees
    (jamais remplacees silencieusement en cas de collision : l'appelant
    doit explicitement reprendre `GENERIC_FUNCTIONS` s'il veut les garder)
    par `functions` si fourni (ex. les fonctions metier de
    `payroll.services.expr`, ou l'environnement volontairement minimal
    d'une condition de flux `automation`)."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise RestrictedExpressionError(f"Expression invalide : {exc}") from exc
    allowed_functions = dict(GENERIC_FUNCTIONS)
    if functions:
        allowed_functions.update(functions)
    return _eval_node(tree.body, variables, allowed_functions)


def _eval_node(  # noqa: C901, PLR0911
    node: ast.AST, variables: dict[str, Any], functions: dict[str, Any]
) -> Any:  # noqa: ANN401
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, str, bool)) or node.value is None:
            return node.value
        raise RestrictedExpressionError(f"Constante non autorisee : {node.value!r}")
    if isinstance(node, ast.Name):
        if node.id in variables:
            return variables[node.id]
        if node.id in functions:
            return functions[node.id]
        raise RestrictedExpressionError(f"Variable inconnue : '{node.id}'")
    if isinstance(node, ast.BinOp):
        op = _ALLOWED_BINOPS.get(type(node.op))
        if op is None:
            raise RestrictedExpressionError(f"Operateur non autorise : {type(node.op).__name__}")
        left_value = _eval_node(node.left, variables, functions)
        right_value = _eval_node(node.right, variables, functions)
        return op(left_value, right_value)
    if isinstance(node, ast.UnaryOp):
        op = _ALLOWED_UNARYOPS.get(type(node.op))
        if op is None:
            raise RestrictedExpressionError(
                f"Operateur unaire non autorise : {type(node.op).__name__}"
            )
        return op(_eval_node(node.operand, variables, functions))
    if isinstance(node, ast.BoolOp):
        values = [_eval_node(v, variables, functions) for v in node.values]
        return all(values) if isinstance(node.op, ast.And) else any(values)
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, variables, functions)
        for comparator_op, comparator in zip(node.ops, node.comparators, strict=True):
            op = _ALLOWED_COMPARE.get(type(comparator_op))
            if op is None:
                raise RestrictedExpressionError(
                    f"Comparaison non autorisee : {type(comparator_op).__name__}"
                )
            right = _eval_node(comparator, variables, functions)
            if not op(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return (
            _eval_node(node.body, variables, functions)
            if _eval_node(node.test, variables, functions)
            else _eval_node(node.orelse, variables, functions)
        )
    if isinstance(node, ast.Subscript):
        value = _eval_node(node.value, variables, functions)
        key = _eval_node(node.slice, variables, functions)
        if not isinstance(value, (dict, list, tuple)):
            raise RestrictedExpressionError("Acces indexe non autorise sur ce type.")
        try:
            return value[key]
        except (KeyError, IndexError, TypeError):
            return None
    if isinstance(node, ast.Attribute):
        # Aucun objet Python arbitraire n'est jamais expose a l'evaluateur
        # — l'acces attribut generique reste interdit dans tous les cas.
        raise RestrictedExpressionError(f"Acces attribut non autorise : '.{node.attr}'")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in functions:
            raise RestrictedExpressionError("Appel de fonction non autorise.")
        func = functions[node.func.id]
        args = [_eval_node(a, variables, functions) for a in node.args]
        return func(*args)
    if isinstance(node, ast.List):
        return [_eval_node(e, variables, functions) for e in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval_node(e, variables, functions) for e in node.elts)
    if isinstance(node, ast.Dict):
        return {
            _eval_node(k, variables, functions): _eval_node(v, variables, functions)
            for k, v in zip(node.keys, node.values, strict=True)
            if k is not None
        }
    # Tout le reste (Import/ImportFrom, Lambda, comprehensions, walrus,
    # Attribute generique deja traite ci-dessus, appel de methode, etc.)
    # est explicitement REFUSE — liste d'autorisation, jamais de refus.
    raise RestrictedExpressionError(f"Construction non autorisee : {type(node).__name__}")
