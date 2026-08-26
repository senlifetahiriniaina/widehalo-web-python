"""RG-PAT-1 (gradation) et RG-PAT-2 (controle de coherence/monotonie).

Gradation en 3 modes conceptuels (le CDC distingue `increment_fixe` et
`increment_progressif` uniquement par le decoupage des plages
`from_size`/`to_size` — mecaniquement identiques, un increment additif par
etape de taille — plus `pourcentage` (multiplicatif) et `formule`
(expression sur d'autres points de mesure de la MEME taille, evaluee apres
les 3 premiers modes)."""

from __future__ import annotations

import ast
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.patronage.models import PatGradingRule, PatSizeChart


def _safe_eval_formula(formula: str, variables: dict[str, Decimal]) -> Decimal:
    """Evaluateur restreint (pas de `eval()` sur une entree utilisateur) :
    seuls noms de variables, nombres, +-*/ et parentheses sont autorises."""
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        raise ValidationError(_("Formule de gradation invalide.")) from exc

    def _evaluate(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Expression):
            return _evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return Decimal(str(node.value))
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise ValidationError(
                    _("Point de mesure inconnu dans la formule : %(name)s") % {"name": node.id}
                )
            return variables[node.id]
        if isinstance(node, ast.BinOp):
            left, right = _evaluate(node.left), _evaluate(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
        if isinstance(node, ast.UnaryOp):
            operand = _evaluate(node.operand)
            if isinstance(node.op, ast.UAdd):
                return operand
            if isinstance(node.op, ast.USub):
                return -operand
        raise ValidationError(_("Formule de gradation invalide."))

    return _evaluate(tree)


def _rule_for_step(
    rules: list[PatGradingRule], sizes: list[str], from_index: int, to_index: int
) -> PatGradingRule | None:
    for rule in rules:
        rule_from = sizes.index(rule.from_size) if rule.from_size in sizes else -1
        rule_to = sizes.index(rule.to_size) if rule.to_size in sizes else -1
        if rule_from <= from_index and to_index <= rule_to:
            return rule
    return None


def apply_grading(size_chart: PatSizeChart) -> dict[str, dict[str, Decimal]]:
    """Retourne `{measurement_point_code: {size: value}}` pour toutes les
    tailles de la grille, a partir des valeurs de la taille de base et des
    regles de gradation."""
    sizes: list[str] = size_chart.sizes
    if size_chart.base_size not in sizes:
        raise ValidationError(_("La taille de base ne fait pas partie des tailles de la grille."))
    base_index = sizes.index(size_chart.base_size)

    base_values = {
        v.measurement_point.code: (v.measurement_point, v.value)
        for v in size_chart.values.filter(size=size_chart.base_size).select_related(
            "measurement_point"
        )
    }
    rules_by_point: dict[str, list[PatGradingRule]] = {}
    formula_rules: dict[str, PatGradingRule] = {}
    for rule in size_chart.grading_rules.select_related("measurement_point").all():
        code = rule.measurement_point.code
        if rule.mode == PatGradingRule.MODE_FORMULA:
            formula_rules[code] = rule
        else:
            rules_by_point.setdefault(code, []).append(rule)

    results: dict[str, dict[str, Decimal]] = {}

    # 1) modes additif/multiplicatif, en s'eloignant de la taille de base
    # dans les deux sens.
    for code, (_point, base_value) in base_values.items():
        rules = rules_by_point.get(code, [])
        values: dict[str, Decimal] = {size_chart.base_size: base_value}

        current = base_value
        for i in range(base_index + 1, len(sizes)):
            forward_rule = _rule_for_step(rules, sizes, i - 1, i)
            current = _apply_step(current, forward_rule)
            values[sizes[i]] = current

        current = base_value
        for i in range(base_index - 1, -1, -1):
            backward_rule = _rule_for_step(rules, sizes, i, i + 1)
            current = _apply_step(current, backward_rule, reverse=True)
            values[sizes[i]] = current

        results[code] = values

    # 2) formules, evaluees apres coup pour chaque taille (dependent des
    # valeurs deja resolues a l'etape 1).
    for code, rule in formula_rules.items():
        values = {}
        for size in sizes:
            variables = {
                pt_code: pt_values[size]
                for pt_code, pt_values in results.items()
                if size in pt_values
            }
            values[size] = _safe_eval_formula(rule.formula, variables)
        results[code] = values

    _check_monotonic(results, sizes, base_index)
    return results


def _apply_step(current: Decimal, rule: PatGradingRule | None, *, reverse: bool = False) -> Decimal:
    if rule is None or rule.value is None:
        return current
    if rule.mode == PatGradingRule.MODE_PERCENTAGE:
        factor = Decimal(1) + rule.value / Decimal(100)
        return current / factor if reverse else current * factor
    # increment_fixe / increment_progressif : additif.
    return current - rule.value if reverse else current + rule.value


def _check_monotonic(
    results: dict[str, dict[str, Decimal]], sizes: list[str], base_index: int
) -> None:
    """RG-PAT-2 : verifie la monotonie des mesures entre tailles
    successives (une taille L ne doit jamais etre plus etroite qu'une M)."""
    for code, values in results.items():
        ordered = [values[s] for s in sizes if s in values]
        for i in range(1, len(ordered)):
            if ordered[i] < ordered[i - 1]:
                raise ValidationError(
                    _(
                        "Incoherence de gradation detectee pour %(point)s : "
                        "la mesure diminue entre deux tailles successives."
                    )
                    % {"point": code}
                )
