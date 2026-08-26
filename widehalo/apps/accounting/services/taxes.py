"""RG-ACC-5 : un tenant au regime synthetique (impot forfaitaire) ne
collecte pas de TVA — tout champ/etat fiscal correspondant est masque."""

from __future__ import annotations

from apps.accounting.models import AccTax
from apps.core.models.tenant import Tenant


def vat_applicable(tenant: Tenant) -> bool:
    return tenant.fiscal_regime != Tenant.FISCAL_REGIME_SYNTHETIC


def applicable_taxes(tenant: Tenant, *, tax_type: str = AccTax.TYPE_SALE) -> list[AccTax]:
    """Liste des taxes utilisables par ce tenant — vide pour un regime
    synthetique, quelle que soit la configuration de taxes existante."""
    if not vat_applicable(tenant):
        return []
    return list(AccTax.objects.filter(tenant=tenant, type=tax_type))
