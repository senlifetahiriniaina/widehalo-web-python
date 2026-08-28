"""Chargement de la structure salariale de reference Madagascar (PAY-M5,
§5.10.5) depuis une fixture JSON MODIFIABLE — meme patron que
`apps.accounting.services.<...>.load_pcg2005`/`pcg2005_mg.json`.

**RESERVE, meme discipline que le PCG2005/§5.10.3** : cette structure est un
jeu de donnees INITIAL de demonstration (salaire de base, heures sup,
primes, cotisations, IRSA, retenues, net a payer), pas une verite metier
figee — a adapter par tenant avant production."""

from __future__ import annotations

import json
from pathlib import Path

from apps.core.models.tenant import Tenant
from apps.payroll.models import PaySalaryRule, PaySalaryStructure

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "payroll_structure_mg.json"


def load_madagascar_structure(tenant: Tenant) -> PaySalaryStructure:
    """Idempotent (par `(tenant, code)`) — recharge integralement les
    regles si la structure existe deja, pour rester coherent si la fixture
    evolue (meme comportement que `load_pcg2005` sur les comptes)."""
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    struct_data = data["structure"]
    structure, _created = PaySalaryStructure.objects.get_or_create(
        tenant=tenant,
        code=struct_data["code"],
        defaults={"name": struct_data["name"], "country": struct_data["country"]},
    )
    PaySalaryRule.objects.filter(tenant=tenant, structure=structure).delete()
    for rule_data in data["rules"]:
        PaySalaryRule.objects.create(
            tenant=tenant,
            structure=structure,
            sequence=rule_data["sequence"],
            code=rule_data["code"],
            name=rule_data["name"],
            category=rule_data["category"],
            condition_type=rule_data.get("condition_type", PaySalaryRule.CONDITION_ALWAYS),
            condition=rule_data.get("condition", ""),
            amount_type=rule_data["amount_type"],
            amount=rule_data["amount"],
            base_code=rule_data.get("base_code", ""),
            appears_on_payslip=rule_data.get("appears_on_payslip", True),
        )
    return structure
