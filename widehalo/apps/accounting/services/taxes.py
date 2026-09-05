"""RG-ACC-5 : un tenant non assujetti a la TVA n'en collecte pas — tout
champ/etat fiscal correspondant est masque.

**Le defaut ferme par L5.** `vat_applicable` ne comparait qu'au regime
SYNTHETIQUE : elle repondait donc « oui » pour un tenant au regime
`reel_sans_tva`, dont le libelle dit litteralement « Reel, sans
assujettissement TVA ». Les trois regimes de `Tenant.FISCAL_REGIME_CHOICES`
etaient traites comme deux, et le seul des trois qui nomme explicitement la
non-assujettissement etait celui que la fonction declarait assujetti.

Dans le meme mouvement, `Tenant.vat_opted_in` (ACC-SMT1, option
d'assujettissement de la tranche 200-400 M Ar ouverte par la Loi de
Finances 2026) n'etait lu **par rien** dans tout le depot : un champ
documente sur quinze lignes dont aucune decision ne dependait. C'est ici,
et nulle part ailleurs, que cette option a un sens — elle fait basculer un
`reel_sans_tva` du cote assujetti."""

from __future__ import annotations

from apps.accounting.models import AccTax
from apps.core.models.tenant import Tenant


def vat_applicable(tenant: Tenant) -> bool:
    """Ce tenant collecte-t-il la TVA ?

    - `reel_avec_tva` : oui, c'est la definition du regime ;
    - `reel_sans_tva` : non, SAUF option exercee (`vat_opted_in`) ;
    - `synthetique` : jamais — l'impot forfaitaire remplace la TVA, et
      aucune option ne l'ouvre (RG-ACC-5). Un `vat_opted_in` coche par
      erreur sur un tenant synthetique reste donc sans effet, ce qui est
      volontaire : l'option de la Loi de Finances 2026 vise la tranche de
      chiffre d'affaires reel, pas le forfait."""
    if tenant.fiscal_regime == Tenant.FISCAL_REGIME_REAL_WITH_VAT:
        return True
    if tenant.fiscal_regime == Tenant.FISCAL_REGIME_REAL_NO_VAT:
        return bool(tenant.vat_opted_in)
    return False


def applicable_taxes(tenant: Tenant, *, tax_type: str = AccTax.TYPE_SALE) -> list[AccTax]:
    """Liste des taxes utilisables par ce tenant — vide pour un tenant non
    assujetti, quelle que soit la configuration de taxes existante."""
    if not vat_applicable(tenant):
        return []
    return list(AccTax.objects.filter(tenant=tenant, type=tax_type))
