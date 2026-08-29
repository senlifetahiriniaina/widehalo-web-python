"""Contrat public de l'app `payroll` — seule surface que d'autres apps
(futurs modules `reporting`/`strategy`, qui consommeront la masse
salariale) ont le droit d'importer (cf.
tests/architecture/test_module_boundaries.py). Aucun consommateur encore
construit a ce chantier — expose des maintenant les gaps les plus
previsibles (montants agreges, jamais un objet `payroll`), meme discipline
que `presence.services.public` prepare pour ce meme futur module Paie."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
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
