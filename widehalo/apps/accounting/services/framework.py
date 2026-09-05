"""D10 — resolution du referentiel comptable actif d'un tenant.

Applique la regle du cahier §12.2, dans cet ordre exact :
**tenant -> pays -> framework actif -> plan de comptes -> comptes autorises**.

Un repli est conserve pour les tenants anterieurs a D10, dont le pays peut ne
pas porter de `chart_of_accounts_code` : le plan reellement rattache a leurs
comptes fait alors foi. Sans lui, un tenant existant verrait ses etats
financiers disparaitre au deploiement — le referentiel doit etre une donnee,
pas une rupture.
"""

from __future__ import annotations

from apps.accounting.models import AccChartOfAccounts, AccFramework
from apps.core.models.regulatory import CountryDefaultsProfile
from apps.core.models.tenant import Tenant


def framework_for_tenant(tenant: Tenant) -> AccFramework | None:
    """Referentiel comptable actif du tenant, ou `None` si aucun ne repond."""
    profile = CountryDefaultsProfile.objects.filter(country_code=tenant.country_code).first()
    code = (profile.chart_of_accounts_code if profile else "") or ""
    if code:
        framework = AccFramework.objects.filter(code=code, is_active=True).first()
        if framework is not None:
            return framework

    chart = (
        AccChartOfAccounts.objects.filter(accounts__tenant=tenant)
        .select_related("framework")
        .first()
    )
    if chart is not None:
        return chart.framework

    return AccFramework.objects.filter(
        default_country_code=tenant.country_code, is_active=True
    ).first()


def chart_for_country(country_code: str) -> AccChartOfAccounts | None:
    """Plan de comptes charge par defaut a la creation d'un tenant de ce pays
    (critere ACC-1). Resolu par le profil pays, jamais par un nom de commande
    de gestion ecrit en dur cote appelant."""
    profile = CountryDefaultsProfile.objects.filter(country_code=country_code).first()
    code = (profile.chart_of_accounts_code if profile else "") or ""
    if not code:
        return None
    return (
        AccChartOfAccounts.objects.filter(
            framework__code=code, framework__is_active=True, country_code=country_code
        )
        .select_related("framework")
        .first()
    )
