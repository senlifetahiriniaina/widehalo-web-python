"""FIN2 — scenario de prevision (`FinForecastScenario`/`FinForecastScenarioLine`).

Deux gaps `services.public` REELS, verifies dans le code source de chaque
module avant d'etre appeles (jamais devines, cf. plan) :
- `apps.payroll.services.public.get_payroll_mass_projection(tenant, *, months)`
  -> `list[dict[str, Decimal]]` avec les cles `month_index`/`total_wage_base`/
  `total_employer_social` (verifie dans `apps/payroll/services/public.py`).
- `apps.accounting.services.public.get_treasury_forecast_summary(tenant, *,
  as_of_date, horizon_days)` -> `dict[str, Any]` avec une cle `"buckets"`
  (liste de dicts `period_label`/`period_start`/`period_end`/
  `projected_balance_mga`, verifie dans `apps/accounting/services/reports.py::
  treasury_forecast`).

`sales.services.public.get_forecast_summary` (prevision de VENTE) n'est PAS
appele ici — cf. docstring `models.py::FinForecastScenario` pour la
disclosure complete (prevision en unites, pas en MGA, `catalog` non declare
comme dependance)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.services.sequences import next_reference
from apps.financing.models import FinForecastScenario, FinForecastScenarioLine, FinLoanApplication


def create_scenario(
    tenant: Tenant,
    *,
    name: str,
    period_start: dt.date,
    period_end: dt.date,
    loan_application: FinLoanApplication | None = None,
    notes: str = "",
) -> FinForecastScenario:
    if period_end < period_start:
        raise ValidationError(_("La fin de periode doit etre posterieure au debut."))
    reference = next_reference(tenant, "FINFCST", period_start.year)
    return FinForecastScenario.objects.create(
        tenant=tenant,
        reference=reference,
        loan_application=loan_application,
        name=name,
        period_start=period_start,
        period_end=period_end,
        notes=notes,
    )


def add_scenario_line(
    scenario: FinForecastScenario,
    *,
    statement_type: str,
    label: str,
    period: str,
    amount_mga: Decimal,
    source: str = FinForecastScenarioLine.SOURCE_MANUAL,
) -> FinForecastScenarioLine:
    valid_statement_types = {choice[0] for choice in FinForecastScenario.STATEMENT_CHOICES}
    if statement_type not in valid_statement_types:
        raise ValidationError(_("Type d'etat financier previsionnel invalide."))
    return FinForecastScenarioLine.objects.create(
        tenant=scenario.tenant,
        scenario=scenario,
        statement_type=statement_type,
        label=label,
        period=period,
        amount_mga=amount_mga,
        source=source,
    )


@transaction.atomic
def populate_income_statement_from_payroll_projection(
    scenario: FinForecastScenario, tenant: Tenant, *, months: int = 12
) -> list[FinForecastScenarioLine]:
    """Regenere les lignes `source=payroll_projection` de ce scenario
    (supprime puis recree, jamais un cumul incremental a chaque appel) a
    partir de `payroll.services.public.get_payroll_mass_projection` —
    montants NEGATIFS (convention de signe documentee sur
    `FinForecastScenarioLine`, ce sont des charges)."""
    from apps.payroll.services.public import get_payroll_mass_projection

    scenario.lines.filter(source=FinForecastScenarioLine.SOURCE_PAYROLL_PROJECTION).delete()
    projections = get_payroll_mass_projection(tenant, months=months)
    created: list[FinForecastScenarioLine] = []
    for row in projections:
        month_offset = int(row["month_index"]) - 1
        period = (scenario.period_start + relativedelta(months=month_offset)).strftime("%Y-%m")
        total_charge = row["total_wage_base"] + row["total_employer_social"]
        created.append(
            add_scenario_line(
                scenario,
                statement_type=FinForecastScenario.STATEMENT_INCOME,
                label=str(_("Charges de personnel previsionnelles")),
                period=period,
                amount_mga=-total_charge,
                source=FinForecastScenarioLine.SOURCE_PAYROLL_PROJECTION,
            )
        )
    return created


@transaction.atomic
def populate_cash_flow_from_treasury_forecast(
    scenario: FinForecastScenario,
    tenant: Tenant,
    *,
    as_of_date: dt.date | None = None,
    horizon_days: int = 90,
) -> list[FinForecastScenarioLine]:
    """Regenere les lignes `source=treasury_forecast` (supprime puis recree)
    a partir de `accounting.services.public.get_treasury_forecast_summary`
    (ACC-TRESO/A15, paniers hebdomadaires) — une ligne `cash_flow` par
    panier, `amount_mga` = solde PROJETE CUMULE du panier (pas un flux net
    du panier isole), coherent avec la semantique de `treasury_forecast`."""
    from apps.accounting.services.public import get_treasury_forecast_summary

    scenario.lines.filter(source=FinForecastScenarioLine.SOURCE_TREASURY_FORECAST).delete()
    summary = get_treasury_forecast_summary(
        tenant, as_of_date=as_of_date, horizon_days=horizon_days
    )
    created: list[FinForecastScenarioLine] = []
    for bucket in summary["buckets"]:
        period = bucket["period_start"].strftime("%Y-%m")
        created.append(
            add_scenario_line(
                scenario,
                statement_type=FinForecastScenario.STATEMENT_CASH_FLOW,
                label=bucket["period_label"],
                period=period,
                amount_mga=bucket["projected_balance_mga"],
                source=FinForecastScenarioLine.SOURCE_TREASURY_FORECAST,
            )
        )
    return created
