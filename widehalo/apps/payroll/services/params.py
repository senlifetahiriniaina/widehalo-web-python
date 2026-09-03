"""Resolution typee des parametres reglementaires §5.10.3 — enveloppe
`apps.core.services.regulatory.get_parameter` (reutilise tel quel) en
convertissant les valeurs JSON en `Decimal` (jamais `float`, convention du
depot). **PAY-M3 (piege classique explicitement teste, test d'acceptance
n°4)** : tout appelant DOIT resoudre ces parametres a la date de la
PERIODE de paie, jamais a la date du calcul — chaque fonction ci-dessous
prend `at_date` en parametre obligatoire, aucun defaut sur `date.today()`."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from apps.core.models.tenant import Tenant
from apps.core.services.regulatory import get_parameter
from apps.payroll.services.seed import (
    CODE_CNAPS_RATE,
    CODE_FMFP_RATE,
    CODE_IRSA_BRACKETS,
    CODE_IRSA_DEPENDENT_REDUCTION,
    CODE_IRSA_MINIMUM,
    CODE_OSTIE_RATE,
    CODE_OVERTIME_EXEMPT_HOURS,
    CODE_SME,
    CODE_SOCIAL_CEILING_MULTIPLIER,
)


@dataclass(frozen=True)
class IrsaBracket:
    min_amount: Decimal
    max_amount: Decimal | None
    rate: Decimal


@dataclass(frozen=True)
class PayrollParams:
    """Instantane immuable de tous les parametres §5.10.3 resolus a UNE
    date (celle de la periode de paie, PAY-M3) — c'est cet objet, jamais
    des appels epars a `get_parameter`, que le moteur de regles recoit sous
    la cle `params` de l'environnement PAY-M2."""

    at_date: dt.date
    irsa_brackets: tuple[IrsaBracket, ...]
    irsa_minimum: Decimal
    irsa_dependent_reduction: Decimal
    cnaps_employer_rate: Decimal
    cnaps_employee_rate: Decimal
    ostie_employer_rate: Decimal
    ostie_employee_rate: Decimal
    fmfp_employer_rate: Decimal
    sme: Decimal
    social_ceiling_multiplier: Decimal
    overtime_exempt_hours: Decimal

    @property
    def social_ceiling(self) -> Decimal:
        """RG-PAY-2 : plafond de cotisation = 8 x SME, resolu a la date de
        la periode."""
        return self.sme * self.social_ceiling_multiplier


def resolve_params(tenant: Tenant, at_date: dt.date) -> PayrollParams:
    brackets_raw = get_parameter(CODE_IRSA_BRACKETS, at_date, tenant=tenant)
    brackets = tuple(
        IrsaBracket(
            min_amount=Decimal(b["min"]),
            max_amount=Decimal(b["max"]) if b["max"] is not None else None,
            rate=Decimal(b["rate"]),
        )
        for b in brackets_raw
    )
    minimum = Decimal(get_parameter(CODE_IRSA_MINIMUM, at_date, tenant=tenant)["amount"])
    reduction = Decimal(
        get_parameter(CODE_IRSA_DEPENDENT_REDUCTION, at_date, tenant=tenant)["amount"]
    )
    cnaps = get_parameter(CODE_CNAPS_RATE, at_date, tenant=tenant)
    ostie = get_parameter(CODE_OSTIE_RATE, at_date, tenant=tenant)
    fmfp = get_parameter(CODE_FMFP_RATE, at_date, tenant=tenant)
    sme = Decimal(get_parameter(CODE_SME, at_date, tenant=tenant)["amount"])
    ceiling_multiplier = Decimal(
        get_parameter(CODE_SOCIAL_CEILING_MULTIPLIER, at_date, tenant=tenant)["multiplier"]
    )
    overtime_exempt = Decimal(
        get_parameter(CODE_OVERTIME_EXEMPT_HOURS, at_date, tenant=tenant)["hours"]
    )
    return PayrollParams(
        at_date=at_date,
        irsa_brackets=brackets,
        irsa_minimum=minimum,
        irsa_dependent_reduction=reduction,
        cnaps_employer_rate=Decimal(cnaps["employer"]),
        cnaps_employee_rate=Decimal(cnaps["employee"]),
        ostie_employer_rate=Decimal(ostie["employer"]),
        ostie_employee_rate=Decimal(ostie["employee"]),
        fmfp_employer_rate=Decimal(fmfp["employer"]),
        sme=sme,
        social_ceiling_multiplier=ceiling_multiplier,
        overtime_exempt_hours=overtime_exempt,
    )


def compute_irsa_bracket_tax(taxable_base: Decimal, params: PayrollParams) -> Decimal:
    """Applique UNIQUEMENT le bareme 6 tranches PROGRESSIF (chaque tranche
    taxee sur sa seule portion, pas un taux marginal unique applique a toute
    la base) + le minimum de perception (floor, jamais une ligne additive
    distincte — RG-PAY-1/§5.10.5) — SANS la reduction pour personne a
    charge, calculee separement (cf. `apps.payroll.services.expr.
    irsa_tranche`, meme formule, utilisee par le moteur de regles PAY-M1 sur
    des dict/Decimal bruts plutot que sur ce dataclass — duplication
    volontaire minime entre les 2 points d'entree, disclosed, verifiee
    identique par les tests d'acceptance §5.10.10 n°1/2/3 qui exercent les
    DEUX chemins).

    `taxable_base` doit deja etre arrondie a la centaine inferieure par
    l'appelant (RG-PAY-1 : "Base IRSA = Brut - cotisations salariales,
    arrondie a la centaine inferieure")."""
    tax = Decimal(0)
    for bracket in params.irsa_brackets:
        if taxable_base < bracket.min_amount:
            continue
        upper = bracket.max_amount if bracket.max_amount is not None else taxable_base
        # `min_amount` de chaque palier est deja la 1ere valeur imposable a
        # ce taux (350001, 400001...) sauf le tout premier (0) — la largeur
        # imposee au taux du palier est donc [min_amount, min(base, upper)]
        # inclus des 2 cotes : min(base, upper) - min_amount + 1 Ar.
        portion = min(taxable_base, upper) - bracket.min_amount + Decimal(1)
        if portion <= 0:
            continue
        tax += portion * bracket.rate
    if taxable_base <= 0:
        return Decimal(0)
    return max(tax, params.irsa_minimum)
