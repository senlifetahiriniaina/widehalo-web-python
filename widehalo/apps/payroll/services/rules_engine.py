"""Moteur de regles §5.10.5 — s'inspire CONCEPTUELLEMENT du moteur d'Odoo
(structure salariale -> regles sequencees -> categories -> expressions)
SANS reutilisation de code (aucune dependance sur `odoo`/son code source,
reimplementation complete et independante).

PAY-M2 : variables explicitement declarees disponibles aux expressions —
`contract`, `employee`, `payslip`, `worked_days`, `absences`, `overtime`,
`benefits`, `params`, `result_rules` (resultats des regles deja calculees
DANS LA MEME PASSE, dans l'ordre de `sequence` — jamais les regles
suivantes, qui n'existent pas encore a ce point de la boucle)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from apps.payroll.models import PaySalaryRule, PaySalaryStructure
from apps.payroll.services.expr import safe_eval


@dataclass
class RuleResult:
    rule: PaySalaryRule
    amount: Decimal
    base: Decimal
    rate: Decimal | None


def _ordered_rules(structure: PaySalaryStructure) -> list[PaySalaryRule]:
    """Resout les regles d'UNE structure, en incluant celles heritees via
    `parent` (regles du parent d'abord, puis les siennes, chacune triee par
    `sequence` — l'heritage n'est qu'une facilite de composition, jamais un
    override implicite d'un `code` deja present chez le parent : un `code`
    duplique entre parent et enfant produit 2 lignes distinctes, assume et
    simple plutot qu'une resolution d'override non demandee par le CDC)."""
    chain: list[PaySalaryStructure] = []
    current: PaySalaryStructure | None = structure
    seen: set[Any] = set()
    while current is not None and current.id not in seen:
        chain.append(current)
        seen.add(current.id)
        current = current.parent
    rules: list[PaySalaryRule] = []
    for struct in reversed(chain):
        rules.extend(struct.rules.order_by("sequence"))
    return rules


def _condition_met(rule: PaySalaryRule, variables: dict[str, Any]) -> bool:
    if rule.condition_type == PaySalaryRule.CONDITION_ALWAYS:
        return True
    if rule.condition_type == PaySalaryRule.CONDITION_PYTHON:
        return bool(safe_eval(rule.condition, variables))
    if rule.condition_type == PaySalaryRule.CONDITION_RANGE:
        spec = json.loads(rule.condition)
        value = variables["result_rules"].get(spec["base_code"], Decimal(0))
        lo = Decimal(str(spec["min"])) if spec.get("min") is not None else None
        hi = Decimal(str(spec["max"])) if spec.get("max") is not None else None
        if lo is not None and value < lo:
            return False
        return not (hi is not None and value > hi)
    raise ValueError(f"condition_type inconnu : {rule.condition_type}")


def _amount_for(
    rule: PaySalaryRule, variables: dict[str, Any]
) -> tuple[Decimal, Decimal, Decimal | None]:
    """Retourne (amount, base, rate)."""
    result_rules: dict[str, Decimal] = variables["result_rules"]
    base = result_rules.get(rule.base_code, Decimal(0)) if rule.base_code else Decimal(0)
    if rule.amount_type == PaySalaryRule.AMOUNT_FIXED:
        return Decimal(rule.amount or "0"), base, None
    if rule.amount_type == PaySalaryRule.AMOUNT_PERCENT:
        rate = Decimal(rule.amount or "0")
        return (base * rate).quantize(Decimal("0.0001")), base, rate
    if rule.amount_type == PaySalaryRule.AMOUNT_PYTHON:
        value = safe_eval(rule.amount, variables)
        return Decimal(str(value)), base, None
    raise ValueError(f"amount_type inconnu : {rule.amount_type}")


def evaluate_structure(
    structure: PaySalaryStructure, variables: dict[str, Any]
) -> list[RuleResult]:
    """PAY-M3 : purement fonctionnel de `variables` (qui embarque `params`,
    deja resolu par l'appelant a la date de la PERIODE — jamais recalcule
    ici) -> aucun acces horloge/date du jour, deterministe et reproductible
    par construction."""
    variables = dict(variables)
    result_rules: dict[str, Decimal] = {}
    variables["result_rules"] = result_rules
    results: list[RuleResult] = []
    for rule in _ordered_rules(structure):
        if not _condition_met(rule, variables):
            continue
        amount, base, rate = _amount_for(rule, variables)
        result_rules[rule.code] = amount
        results.append(RuleResult(rule=rule, amount=amount, base=base, rate=rate))
    return results
