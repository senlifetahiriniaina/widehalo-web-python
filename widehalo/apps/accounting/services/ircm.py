"""ACC-IRCM (§1.7 du document annexe) : declaration annuelle de l'Impot sur
les Revenus des Capitaux Mobiliers — 20% sur les interets/revenus et produits
des obligations et emprunts, applicable uniquement aux entreprises au regime
reel (IR). Assiette reutilisee VERBATIM depuis `services/reports.py` : les
comptes de produits financiers classe 76-77, deja la ligne "Produits
financiers" d'`income_statement` (A9) — pas de reimplementation de cette
plage de comptes.

Reserve OECFM/DGI (§0.5, §3.5 du document annexe) : le taux de 20% et
l'echeance du 15 mai N+1 sont repris d'un document non primaire, a confirmer
aupres d'un expert-comptable OECFM ou de la DGI avant tout usage en
production reelle. `rate_pct` reste un champ modifiable par declaration
(cf. `AccIrcmDeclaration`) plutot qu'une constante Python figee, precisement
pour absorber une correction sans deploiement — un sourcage complet via
`apps.core.services.regulatory.RegulatoryParameter` serait l'etape suivante
naturelle (le mecanisme existe deja au niveau `core`) mais est laisse hors
V1 : ce module ne dispose pas encore d'un jeu de parametres fiscaux
malgaches verifies a y enregistrer, et l'introduire pour ce seul taux
introduirait une dependance disproportionnee pour un gain V1 marginal (un
defaut de champ documente et corrigible resout deja le besoin immediat)."""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils.translation import gettext as _

from apps.accounting.models import AccFiscalYear, AccIrcmDeclaration, AccMove, AccMoveLine
from apps.accounting.services.framework import framework_for_tenant
from apps.core.models.tenant import Tenant
from apps.core.services.sequences import next_reference

_REAL_REGIMES = (Tenant.FISCAL_REGIME_REAL_NO_VAT, Tenant.FISCAL_REGIME_REAL_WITH_VAT)

# D10-4 : les prefixes de comptes de produits financiers viennent du
# referentiel (`AccFramework.financial_income_prefixes`) — les litteraux
# "76"/"77" etaient la forme PCG 2005, et echappaient de surcroit a la garde
# ACC-2, dont le motif ne voit pas les codes a deux chiffres.


def generate_ircm_declaration(
    fiscal_year: AccFiscalYear, *, rate_pct: Decimal = Decimal("20")
) -> AccIrcmDeclaration:
    """Genere (ou regenere) la declaration IRCM de l'exercice. Reserve au
    regime reel (`FISCAL_REGIME_REAL_NO_VAT`/`FISCAL_REGIME_REAL_WITH_VAT`) —
    le document annexe restreint explicitement l'IRCM aux "Entreprises au
    regime reel (IR)" (§1.7) ; leve une `ValidationError` i18n pour un
    tenant au regime synthetique, meme discipline que RG-ACC-5
    (`AccTax`)."""
    framework = framework_for_tenant(fiscal_year.tenant)
    financial_prefixes = tuple(framework.financial_income_prefixes) if framework else ()

    tenant = fiscal_year.tenant
    if tenant.fiscal_regime not in _REAL_REGIMES:
        raise ValidationError(
            _(
                "L'IRCM n'est applicable qu'aux entreprises au régime réel — "
                "ce tenant est au régime synthétique."
            )
        )

    balances = (
        AccMoveLine.objects.filter(
            move__period__fiscal_year=fiscal_year, move__state=AccMove.STATE_POSTED
        )
        .values("account__code")
        .annotate(total_debit=Sum("debit"), total_credit=Sum("credit"))
    )
    taxable_base = Decimal(0)
    for entry in balances:
        if financial_prefixes and entry["account__code"].startswith(financial_prefixes):
            debit = entry["total_debit"] or Decimal(0)
            credit = entry["total_credit"] or Decimal(0)
            taxable_base += credit - debit
    if taxable_base < 0:
        taxable_base = Decimal(0)

    amount_due = (taxable_base * rate_pct / Decimal(100)).quantize(Decimal("0.0001"))

    declaration, created = AccIrcmDeclaration.objects.get_or_create(
        tenant=tenant,
        fiscal_year=fiscal_year,
        defaults={
            "taxable_base_mga": taxable_base,
            "rate_pct": rate_pct,
            "amount_due_mga": amount_due,
        },
    )
    if not created:
        declaration.taxable_base_mga = taxable_base
        declaration.rate_pct = rate_pct
        declaration.amount_due_mga = amount_due
        declaration.save(update_fields=["taxable_base_mga", "rate_pct", "amount_due_mga"])
    if not declaration.reference:
        declaration.reference = next_reference(tenant, "IRCM", fiscal_year.date_start.year)
        declaration.save(update_fields=["reference"])
    return declaration
