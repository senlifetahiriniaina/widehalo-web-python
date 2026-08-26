"""SmartDefaults : preconfigure un tenant a sa creation selon le pays
(devise, TVA, fuseau, moyens de paiement...). Jeu Madagascar livre ce lot ;
mecanisme generique pour d'autres pays en V2.

Version complete (CountryDefaultsProfile en base + fixture) livree a
l'etape 10. Le jeu Madagascar est fige ici en constante pour que
`create_tenant --country MG` fonctionne des l'etape 3.
"""

from __future__ import annotations

from typing import Any

from apps.core.models.tenant import Tenant

COUNTRY_DEFAULTS: dict[str, dict[str, Any]] = {
    "MG": {
        "base_currency": "MGA",
        "default_language": "fr",
        "timezone": "Indian/Antananarivo",
        "vat_rate": "20.00",
        "chart_of_accounts_code": "PCG2005",
        "payment_methods": ["cash", "bank_transfer", "mvola", "orange_money", "airtel_money"],
    }
}


def apply_country_defaults(tenant: Tenant, country_code: str) -> Tenant:
    defaults = COUNTRY_DEFAULTS.get(country_code.upper())
    if not defaults:
        return tenant
    tenant.base_currency = defaults["base_currency"]
    tenant.default_language = defaults["default_language"]
    tenant.timezone = defaults["timezone"]
    tenant.retention_policy = tenant.retention_policy or {}
    tenant.retention_policy.setdefault("country_defaults", defaults)
    tenant.save(update_fields=["base_currency", "default_language", "timezone", "retention_policy"])
    return tenant
