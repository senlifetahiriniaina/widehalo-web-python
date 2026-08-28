"""RG-PAY-7 — solde de tout compte (STC) : fin de contrat, indemnite
conges non pris + preavis + indemnite de licenciement le cas echeant.
Reutilise le MEME moteur de regles (PAY-M1..M5) via une structure salariale
dediee "STC" (fixture separee, jamais un service ad hoc qui recalcule a la
main hors du moteur — coherent avec le reste du chantier)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import apps.presence.services.public as presence_public
from apps.core.models.tenant import Tenant
from apps.payroll.models import PayContract, PayPayslip, PayPeriod, PaySalaryStructure
from apps.payroll.services.payslip import compute_payslip

STC_STRUCTURE_CODE = "MG_STC"


def ensure_stc_structure(tenant: Tenant) -> PaySalaryStructure:
    """Structure STC minimaliste : herite de `MG_BASE` (`parent`) pour le
    net du dernier mois travaille, EN PLUS de 2 regles dediees (indemnite
    de conges non pris, preavis). **Simplification assumee (disclosed)** :
    l'indemnite de licenciement proprement dite (calcul par anciennete,
    variable selon la categorie du contrat) n'est pas modelisee en V1 —
    aucune bareme d'indemnite de licenciement n'est fourni par le CDC
    (§5.10.3 ne le liste pas parmi les parametres reglementaires a
    charger) ; seules indemnite conges + preavis sont calculees, une future
    iteration ajoutera un `RegulatoryParameter` dedie si le besoin se
    confirme."""
    from apps.payroll.models import PaySalaryRule

    base = PaySalaryStructure.objects.filter(tenant=tenant, code="MG_BASE").first()
    structure, _created = PaySalaryStructure.objects.get_or_create(
        tenant=tenant,
        code=STC_STRUCTURE_CODE,
        defaults={"name": "Solde de tout compte", "country": "MG", "parent": base},
    )
    if not structure.parent_id and base:
        structure.parent = base
        structure.save(update_fields=["parent"])
    PaySalaryRule.objects.filter(tenant=tenant, structure=structure).delete()
    PaySalaryRule.objects.create(
        tenant=tenant,
        structure=structure,
        sequence=200,
        code="INDEMNITE_CONGE",
        name="Indemnite de conges non pris",
        category=PaySalaryRule.CATEGORY_BASE,
        amount_type=PaySalaryRule.AMOUNT_PYTHON,
        amount=(
            "(contract['wage_base'] / contract['reference_days']) * payslip['leave_balance_days']"
        ),
    )
    PaySalaryRule.objects.create(
        tenant=tenant,
        structure=structure,
        sequence=210,
        code="INDEMNITE_PREAVIS",
        name="Indemnite de preavis",
        category=PaySalaryRule.CATEGORY_BASE,
        amount_type=PaySalaryRule.AMOUNT_PYTHON,
        amount=(
            "(contract['wage_base'] / contract['reference_days']) "
            "* (contract['notice_days'] if not payslip['notice_worked'] else 0)"
        ),
    )
    return structure


def compute_settlement(
    contract: PayContract, *, termination_date: dt.date, notice_worked: bool = False
) -> PayPayslip:
    """Cree/recalcule un bulletin STC (`PayPayslip` rattache a une periode
    dediee couvrant le seul mois de sortie) via le meme moteur PAY-M1..M5,
    en ajoutant deux variables specifiques a l'environnement PAY-M2 : le
    solde de conges restant (`presence.get_leave_balance_remaining_days`) et
    si le preavis a ete effectivement travaille."""
    tenant = contract.tenant
    period, _created = PayPeriod.objects.get_or_create(
        tenant=tenant,
        code=f"STC-{str(contract.employee_id)[:8]}-{termination_date.strftime('%y%m%d')}",
        defaults={
            "date_from": termination_date.replace(day=1),
            "date_to": termination_date,
            "payment_date": termination_date,
        },
    )
    stc_structure = ensure_stc_structure(tenant)
    stc_contract = PayContract.objects.filter(
        tenant=tenant,
        employee_id=contract.employee_id,
        parent_contract=contract,
        type=contract.type,
    ).first()
    working_contract = stc_contract or contract

    leave_balance = presence_public.get_leave_balance_remaining_days(
        tenant,
        contract.employee_id,
        year=termination_date.year,
        absence_type_code="conge_paye",
    )
    payslip, _created = PayPayslip.objects.update_or_create(
        tenant=tenant,
        employee_id=contract.employee_id,
        period=period,
        defaults={
            "contract": working_contract,
            "date_from": period.date_from,
            "date_to": period.date_to,
        },
    )
    payslip.overtime_hours = {}

    # `contract.salary_structure` bascule temporairement sur `MG_STC`
    # (heritage de `MG_BASE` via `parent`) le temps du calcul — restaure
    # ensuite, jamais persiste sur le contrat d'origine.
    original_structure_id = working_contract.salary_structure_id
    working_contract.salary_structure = stc_structure
    try:
        return compute_payslip(
            payslip,
            extra_payslip_vars={
                "leave_balance_days": leave_balance or Decimal(0),
                "notice_worked": notice_worked,
            },
        )
    finally:
        working_contract.salary_structure_id = original_structure_id
