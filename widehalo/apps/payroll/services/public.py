"""Contrat public de l'app `payroll` — seule surface que d'autres apps
(futurs modules `reporting`/`strategy`, qui consommeront la masse
salariale) ont le droit d'importer (cf.
tests/architecture/test_module_boundaries.py). Aucun consommateur encore
construit a ce chantier — expose des maintenant les gaps les plus
previsibles (montants agreges, jamais un objet `payroll`), meme discipline
que `presence.services.public` prepare pour ce meme futur module Paie.

Bloc Transverse, T4 (FOR-11) : `list_published_payslips_for_warehouse`,
premier consommateur reel de ce contrat — `apps.analytics.AnFactPaie`."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models import Sum

from apps.core.models.tenant import Tenant
from apps.payroll.models import PayPayslip, PayPeriod


def get_total_net_payroll_for_period(tenant: Tenant, period_code: str) -> Decimal | None:
    """Masse salariale nette totale d'une periode VALIDEE/PAYEE/CLOTUREE —
    `None` si la periode est inconnue ou pas encore validee (jamais un
    montant partiel d'une periode toujours en calcul)."""
    period = PayPeriod.objects.filter(tenant=tenant, code=period_code).first()
    if period is None or period.state not in (
        PayPeriod.STATE_VALIDATED,
        PayPeriod.STATE_PAID,
        PayPeriod.STATE_CLOSED,
    ):
        return None
    total = period.payslips.exclude(state=PayPayslip.STATE_CANCELLED).aggregate(
        total=Sum("net_to_pay")
    )["total"]
    return total if total is not None else Decimal(0)


def is_employee_on_payroll(tenant: Tenant, employee_id: UUID, *, at_date: dt.date) -> bool:
    """Un employe a-t-il un contrat de paie ACTIF a cette date — gap
    previsible pour un futur module `reporting` (effectif paye)."""
    from apps.payroll.services.contracts import resolve_active_contract

    return resolve_active_contract(tenant, employee_id, at_date=at_date) is not None


def get_payroll_mass_projection(tenant: Tenant, *, months: int = 12) -> list[dict[str, Decimal]]:
    """Nouveau gap ajoute pendant le chantier `strategy` (rapport business
    plan, section prevision, PAY-PROJ1) : mise a plat tabulaire de
    `services/projection.py::project_payroll_mass` (calculateur SIMPLE deja
    construit, EFFECTIF CONSTANT, sans augmentation planifiee) — aucun
    nouveau calcul ici, primitives en sortie (jamais un objet
    `MonthProjection`)."""
    from apps.payroll.services.projection import project_payroll_mass

    projections = project_payroll_mass(tenant, months=months)
    return [
        {
            "month_index": Decimal(projection.month_index),
            "total_wage_base": projection.total_wage_base,
            "total_employer_social": projection.total_employer_social,
        }
        for projection in projections
    ]


def list_published_payslips_for_warehouse(
    tenant: Tenant, *, updated_since: Any = None
) -> list[dict[str, Any]]:
    """Bloc Transverse, T4 (FOR-11) : extrait les `PayPayslip` PUBLIÉS
    (`state in (approved, paid)` — même définition exacte que le
    docstring "publié" de `PayPayslip`, Bloc E/E9/PAY-8) pour alimenter
    `apps.analytics.AnFactPaie` — seule voie d'accès pour `analytics`,
    qui ne doit jamais importer `apps.payroll.models` (règle de couplage
    n°1).

    `updated_since` (datetime ou None) filtre sur `PayPayslip.updated_at`
    STRICTEMENT supérieur — même contrat exact que
    `stocks.services.public.list_moves_for_warehouse`. Renvoie des dicts
    primitifs, jamais l'objet `PayPayslip`.

    **`net_to_pay` (RG-PAY-9, chiffré individuellement à la source)
    volontairement ABSENT de ce dict** : l'exposer en clair dans un
    entrepôt de données généraliste, consultable par d'autres rôles via
    `apps.bi`, contredirait directement la discipline de cloisonnement
    déjà actée au chantier P5 ("cloisonnement paie transverse") — seuls
    les composants de COÛT employeur (brut, base imposable, charges
    salariale/patronale) sont exposés ici, jamais le net à payer
    individuel d'un salarié.

    `regulatory_parameter_versions` : repris de la première ligne du
    bulletin (`PayPayslipLine.regulatory_parameter_versions`, Bloc E, E3,
    PAY-4) — même instantané sur toutes les lignes d'un même bulletin
    (cf. sa docstring), donc n'importe laquelle convient ; dict vide si
    le bulletin n'a exceptionnellement aucune ligne."""
    payslips = (
        PayPayslip.objects.filter(
            tenant=tenant, state__in=(PayPayslip.STATE_APPROVED, PayPayslip.STATE_PAID)
        )
        .select_related("period")
        .prefetch_related("lines")
    )
    if updated_since is not None:
        payslips = payslips.filter(updated_at__gt=updated_since)
    results: list[dict[str, Any]] = []
    for payslip in payslips:
        lines = list(payslip.lines.all())
        regulatory_parameter_versions = lines[0].regulatory_parameter_versions if lines else {}
        results.append(
            {
                "payslip_id": payslip.id,
                "updated_at": payslip.updated_at,
                "date": payslip.date_to,
                "employee_id": payslip.employee_id,
                "period_code": payslip.period.code,
                "reference": payslip.reference,
                "state": payslip.state,
                "gross": payslip.gross,
                "taxable_base": payslip.taxable_base,
                "irsa": payslip.irsa,
                "social_employee": payslip.social_employee,
                "social_employer": payslip.social_employer,
                "payment_method": payslip.payment_method,
                "regulatory_parameter_versions": regulatory_parameter_versions,
            }
        )
    return results
