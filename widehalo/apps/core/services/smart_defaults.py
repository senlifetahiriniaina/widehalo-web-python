"""SmartDefaults : preconfigure un tenant a sa creation selon le pays
(devise, TVA, fuseau, moyens de paiement...), lu depuis
`CountryDefaultsProfile` en base (jamais en dur dans le code) — extensible
a d'autres pays que Madagascar par simple ajout de donnees, sans
modification du code applicatif ni des futurs modules metier."""

from __future__ import annotations

from apps.core.models.regulatory import CountryDefaultsProfile
from apps.core.models.tenant import Tenant


def apply_country_defaults(tenant: Tenant, country_code: str) -> Tenant:
    profile = CountryDefaultsProfile.objects.filter(country_code=country_code.upper()).first()
    if profile is None:
        return tenant

    tenant.base_currency = profile.base_currency
    tenant.default_language = profile.default_language
    tenant.timezone = profile.timezone
    tenant.retention_policy = tenant.retention_policy or {}
    tenant.retention_policy.setdefault(
        "country_defaults",
        {
            "vat_rate": str(profile.vat_rate) if profile.vat_rate is not None else None,
            "chart_of_accounts_code": profile.chart_of_accounts_code,
            "payment_methods": profile.payment_methods,
        },
    )
    tenant.save(update_fields=["base_currency", "default_language", "timezone", "retention_policy"])
    return tenant
