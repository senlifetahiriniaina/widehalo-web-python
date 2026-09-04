"""PAY-PROJ1 (§5.10.11, "Projection de masse salariale", verdict Adapter) :
calculateur SIMPLE (pas un module de prevision complexe) — projection 12
mois a EFFECTIF CONSTANT + impact des augmentations planifiees."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from apps.core.models.tenant import Tenant
from apps.payroll.models import PayContract


@dataclass(frozen=True)
class MonthProjection:
    month_index: int
    total_wage_base: Decimal
    total_employer_social: Decimal


def project_payroll_mass(
    tenant: Tenant,
    *,
    months: int = 12,
    planned_increases: dict[str, Decimal] | None = None,
    # Bloc E, E2 : ce defaut fige est deliberement exempte du garde-fou
    # `tests/architecture/test_no_hardcoded_payroll_rates.py`
    # (PAYROLL_FILES_ALLOWED_TO_HARDCODE_RATES) — cf. sa propre entree
    # pour la justification complete.
    employer_charge_rate: Decimal = Decimal("0.18"),
) -> list[MonthProjection]:
    """A EFFECTIF CONSTANT : prend les contrats ACTIFS a la date d'appel
    (jamais une simulation d'embauches/departs futurs — hors perimetre
    "calculateur simple" du CDC). `planned_increases` : `{str(contract_id):
    nouveau_wage_base}` applique a partir du mois index (cle
    "<contract_id>:<month_index>") — **simplification assumee (disclosed)**
    : une augmentation planifiee s'applique a partir du mois indique et
    reste valable jusqu'a la fin de la projection, jamais une variation
    intra-mois. `employer_charge_rate` : approxime les charges patronales
    (CNaPS+OSTIE, 13%+5%=18% par defaut, cf. §5.10.3) SANS re-derouler le
    moteur de regles complet ni le plafonnement 8xSME (simplification
    assumee pour un "calculateur simple", disclosed — une projection fine
    re-executerait `compute_payslip` mois par mois pour chaque contrat, hors
    perimetre demande)."""
    planned_increases = planned_increases or {}
    active_contracts = list(
        PayContract.objects.filter(tenant=tenant, state=PayContract.STATE_ACTIVE)
    )
    results: list[MonthProjection] = []
    for month_index in range(1, months + 1):
        total_wage = Decimal(0)
        for contract in active_contracts:
            wage = contract.wage_base
            for key, new_wage in planned_increases.items():
                contract_id_str, _, from_month_str = key.partition(":")
                if contract_id_str == str(contract.id) and month_index >= int(from_month_str):
                    wage = new_wage
            total_wage += wage
        results.append(
            MonthProjection(
                month_index=month_index,
                total_wage_base=total_wage,
                total_employer_social=(total_wage * employer_charge_rate).quantize(Decimal("0.01")),
            )
        )
    return results
