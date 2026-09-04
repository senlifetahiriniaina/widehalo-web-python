"""RG-PAY-1 : chaine de calcul complete d'un bulletin de paie — Presence/
absences -> jours/heures travailles -> salaire de base au prorata -> heures
sup majorees -> primes/avantages -> brut -> cotisations salariales
plafonnees -> base imposable arrondie -> IRSA par tranche -> reductions ->
net imposable -> retenues -> net a payer.

**PAY-M3 (piege classique, test d'acceptance §5.10.10 n°4)** : les
parametres reglementaires sont TOUJOURS resolus a la date de la PERIODE
(`period.date_from`), jamais `datetime.date.today()` — `compute_payslip`
n'appelle JAMAIS `date.today()`/`timezone.now()` pour resoudre un
parametre, garantissant qu'un recalcul en decembre d'une periode de janvier
reproduit EXACTEMENT le meme resultat."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

import apps.presence.services.public as presence_public
from apps.core.models.tenant import Tenant
from apps.payroll.models import PayAdvance, PayContract, PayPayslip, PayPayslipLine, PaySalaryRule
from apps.payroll.services.params import PayrollParams, resolve_params
from apps.payroll.services.rules_engine import RuleResult, evaluate_structure

# Jours ouvrables de reference par mois — convention malgache usuelle (le
# CDC ne fixe pas explicitement cette valeur) : 26 jours, disclosed.
DEFAULT_REFERENCE_DAYS = Decimal(26)
HOURS_PER_DAY = Decimal(8)


def _params_as_expr_dict(params: PayrollParams) -> dict[str, object]:
    return {
        "irsa_brackets": [
            {"min": b.min_amount, "max": b.max_amount, "rate": b.rate} for b in params.irsa_brackets
        ],
        "irsa_minimum": params.irsa_minimum,
        "irsa_dependent_reduction": params.irsa_dependent_reduction,
        "cnaps_employee_rate": params.cnaps_employee_rate,
        "cnaps_employer_rate": params.cnaps_employer_rate,
        "ostie_employee_rate": params.ostie_employee_rate,
        "ostie_employer_rate": params.ostie_employer_rate,
        "fmfp_employer_rate": params.fmfp_employer_rate,
        "sme": params.sme,
        "social_ceiling": params.social_ceiling,
        "overtime_exempt_hours": params.overtime_exempt_hours,
        "overtime_multipliers": params.overtime_multipliers,
    }


def _pending_advance_installment(tenant: Tenant, employee_id: UUID) -> Decimal:
    """Retenue du mois pour les avances en cours de remboursement
    (RG-PAY, retenues) — mensualite = solde restant / mois restants (ne
    depend jamais de l'ordre de calcul des bulletins d'autres employes)."""
    total = Decimal(0)
    for advance in PayAdvance.objects.filter(
        tenant=tenant, employee_id=employee_id, state=PayAdvance.STATE_REPAYING
    ):
        if advance.repayment_months <= 0 or advance.remaining <= 0:
            continue
        installment = min(advance.remaining, advance.remaining / advance.repayment_months)
        total += installment
    return total


@dataclass
class PayslipSimulation:
    """Resultat purement fonctionnel de `simulate_payslip` — AUCUN champ
    ici n'est jamais ecrit en base par cette fonction elle-meme (Bloc E,
    E4/PAY-5 : reutilise tel quel par l'ecran de simulation sur salarie
    temoin, qui ne persiste JAMAIS)."""

    results: list[RuleResult]
    worked_days: Decimal
    absence_summary: list[dict[str, object]]
    overtime_hours: dict[str, object]
    payroll_params: PayrollParams


def simulate_payslip(
    tenant: Tenant,
    contract: PayContract,
    *,
    employee_id: UUID,
    date_from: dt.date,
    date_to: dt.date,
    dependents: int = 0,
    apply_advance_deduction: bool = True,
    overtime_hours: dict[str, object] | None = None,
    extra_payslip_vars: dict[str, object] | None = None,
) -> PayslipSimulation:
    """Coeur PUREMENT FONCTIONNEL de `compute_payslip` (construit
    `variables`, PAY-M2, et appelle `evaluate_structure`) — AUCUNE
    ECRITURE EN BASE ici (ni `PayPayslipLine`, ni mise a jour d'un
    `PayPayslip`). Extrait pour etre reutilise a l'identique par
    `compute_payslip` (qui persiste le resultat) ET par l'ecran de
    simulation de rubrique sur salarie temoin (Bloc E, E4/PAY-5,
    `apps.payroll.views.rubric_simulation`, qui ne persiste jamais) — un
    seul chemin de calcul, jamais deux implementations potentiellement
    divergentes.

    PAY-M3 : `date_from` pilote SEULE la resolution des parametres
    reglementaires (jamais `date.today()`), meme discipline que
    `compute_payslip`."""
    absence_summary = presence_public.get_period_absence_summary(
        tenant, employee_id, date_from=date_from, date_to=date_to
    )
    unjustified_or_paid_absence_days = sum(
        (Decimal(str(a["days"])) for a in absence_summary), Decimal(0)
    )
    # Convention malgache usuelle assumee (le CDC ne fixe pas explicitement
    # cette valeur, disclosed) : un mois de paie complet = `reference_days`
    # jours ouvrables FORFAITAIRES, independamment du nombre reel de jours
    # calendaires de la periode (28/30/31) — pas de prorata calendaire
    # supplementaire, seule l'absence reduit ce forfait.
    reference_days = DEFAULT_REFERENCE_DAYS
    worked_days = max(reference_days - unjustified_or_paid_absence_days, Decimal(0))

    overtime_total_hours = presence_public.get_validated_overtime_hours(
        tenant, employee_id, date_from=date_from, date_to=date_to
    )
    # `presence` n'expose que le TOTAL valide (pas la ventilation par
    # categorie de majoration, cf. docstring `get_validated_overtime_hours`)
    # — la ventilation reelle fournie par l'appelant (via `payslip.
    # overtime_hours` pour un bulletin reel, ou saisie directe pour une
    # simulation) prevaut ; a defaut, tout est impute a la categorie
    # "h_sup_30" par defaut, disclosed.
    resolved_overtime_hours: dict[str, object] = (
        dict(overtime_hours) if overtime_hours else {"h_sup_30": overtime_total_hours}
    )

    hourly_rate = contract.wage_base / (reference_days * HOURS_PER_DAY)

    benefits = [
        {
            "type": b.type,
            "amount": b.amount,
            "is_taxable": b.is_taxable,
            "is_subject_to_social": b.is_subject_to_social,
        }
        for b in contract.benefits.filter(is_active=True)
        if b.date_from is None or b.date_from <= date_to
        if b.date_to is None or b.date_to >= date_from
    ]

    advance_deduction = (
        _pending_advance_installment(tenant, employee_id) if apply_advance_deduction else Decimal(0)
    )

    payslip_vars: dict[str, object] = {"advance_deduction": advance_deduction}
    if extra_payslip_vars:
        payslip_vars.update(extra_payslip_vars)

    # PAY-M3 : resolu UNE SEULE fois, a la date DE REFERENCE (`date_from` —
    # la periode pour un bulletin reel, une date choisie par l'utilisateur
    # pour une simulation). Reutilise a la fois pour l'environnement de
    # formule (`_params_as_expr_dict`) et pour l'instantane de versions
    # trace sur chaque `PayPayslipLine` (Bloc E, E3/PAY-4).
    payroll_params: PayrollParams = resolve_params(tenant, date_from)

    variables: dict[str, object] = {
        "contract": {
            "wage_base": contract.wage_base,
            "wage_type": contract.wage_type,
            "reference_days": reference_days,
            "hourly_rate": hourly_rate,
            "notice_days": Decimal(contract.notice_days),
        },
        "employee": {"id": str(employee_id), "dependents": Decimal(dependents)},
        "payslip": payslip_vars,
        "worked_days": worked_days,
        "absences": absence_summary,
        "overtime": resolved_overtime_hours,
        "benefits": benefits,
        "params": _params_as_expr_dict(payroll_params),
    }

    results = evaluate_structure(contract.salary_structure, variables)
    return PayslipSimulation(
        results=results,
        worked_days=worked_days,
        absence_summary=absence_summary,
        overtime_hours=resolved_overtime_hours,
        payroll_params=payroll_params,
    )


@transaction.atomic
def compute_payslip(
    payslip: PayPayslip,
    *,
    dependents: int = 0,
    apply_advance_deduction: bool = True,
    extra_payslip_vars: dict[str, object] | None = None,
) -> PayPayslip:
    """Calcule (ou RECALCULE) `payslip` a partir de son `contract`/`period`
    deja affectes — remplace integralement les `PayPayslipLine` existantes
    (recalcul idempotent tant que la periode n'est pas VALIDEE, RG-PAY-10).

    `dependents` : nombre de personnes a charge de l'employe — aucun module
    existant ne porte cette donnee (`presence.PrsEmployee` ne la modelise
    pas) ; parametre explicite en attendant une future extension de
    `presence`, disclosed.

    `extra_payslip_vars` : cles additionnelles fusionnees dans
    `variables["payslip"]` (PAY-M2) — utilise par `services.settlement`
    (RG-PAY-7, STC) pour exposer `leave_balance_days`/`notice_worked` aux
    2 regles dediees de la structure `MG_STC` sans dupliquer la logique de
    cette fonction."""
    contract: PayContract = payslip.contract
    tenant = payslip.tenant

    if contract.employee_id != payslip.employee_id:
        raise ValidationError(_("Le contrat ne correspond pas a l'employé du bulletin."))

    simulation = simulate_payslip(
        tenant,
        contract,
        employee_id=payslip.employee_id,
        date_from=payslip.date_from,
        date_to=payslip.date_to,
        dependents=dependents,
        apply_advance_deduction=apply_advance_deduction,
        overtime_hours=payslip.overtime_hours or None,
        extra_payslip_vars=extra_payslip_vars,
    )
    results = simulation.results
    result_by_code = {r.rule.code: r for r in results}
    payroll_params = simulation.payroll_params

    payslip.lines.all().delete()
    for result in results:
        PayPayslipLine.objects.create(
            tenant=tenant,
            payslip=payslip,
            rule=result.rule,
            sequence=result.rule.sequence,
            code=result.rule.code,
            label=result.rule.name,
            category=result.rule.category,
            base=result.base,
            rate=result.rate,
            amount=result.amount,
            is_employer_charge=(
                result.rule.category == PaySalaryRule.CATEGORY_EMPLOYER_CONTRIBUTION
            ),
            regulatory_parameter_versions=payroll_params.versions,
        )

    def _get(code: str) -> Decimal:
        r = result_by_code.get(code)
        return r.amount if r else Decimal(0)

    payslip.worked_days = simulation.worked_days
    payslip.worked_hours = simulation.worked_days * HOURS_PER_DAY
    # JSONField : les `Decimal` ne sont pas serialisables tels quels (le
    # backend Postgres passe par `json.dumps`) — converties en `str` a
    # l'ecriture, jamais un `DjangoJSONEncoder` custom qui perdrait la
    # precision decimale a la relecture.
    payslip.absence_days = [
        {**a, "days": str(a["days"]), "pay_rate_pct": str(a["pay_rate_pct"])}
        for a in simulation.absence_summary
    ]
    payslip.overtime_hours = {k: str(v) for k, v in simulation.overtime_hours.items()}
    payslip.gross = _get("BRUT")
    payslip.taxable_base = _get("BASE_IMPOSABLE")
    payslip.irsa = _get("IRSA_NET")
    payslip.social_employee = _get("CNAPS_SAL") + _get("OSTIE_SAL")
    # FMFP (Sprint 8 / L5 refonte UX, cf.
    # docs/planning/2026-refonte-ux-sprints.md §5) : uniquement part
    # employeur ("FMFP_PAT"), le CDC ne prevoit aucune part salariale —
    # `_get` renvoie 0 tant qu'aucune regle FMFP_PAT n'est configuree sur
    # la structure salariale du tenant (meme discipline que CNAPS/OSTIE,
    # cf. docstring `_get` ci-dessus : jamais une KeyError silencieuse).
    payslip.social_employer = _get("CNAPS_PAT") + _get("OSTIE_PAT") + _get("FMFP_PAT")
    payslip.net_to_pay = _get("NET_A_PAYER")
    payslip.save(
        update_fields=[
            "worked_days",
            "worked_hours",
            "absence_days",
            "overtime_hours",
            "gross",
            "taxable_base",
            "irsa",
            "social_employee",
            "social_employer",
            "net_to_pay",
        ]
    )
    return payslip
