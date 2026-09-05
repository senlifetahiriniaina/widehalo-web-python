"""L3 — le taux de TVA de reference, resolu a la date du document.

**Le defaut que ce module ferme.** `tva.taux_normal` etait reference a
quatre endroits du depot — `apps.simulation.services.baseline`
(`TVA_REGULATORY_CODE`), la docstring de
`core.services.regulatory.get_parameter_with_version`, celle de
`accounting.services.public.get_default_sale_tax`, et le commentaire de
`SimBaseline.regulatory_param_version` — et **seme nulle part**. Ni
migration, ni commande, ni service ne le creait. Consequence verifiee sur
une base de demonstration entierement amorcee : `build_baseline` leve

    Aucun parametre reglementaire 'tva.taux_normal' valide au ... —
    impossible de construire le socle de simulation sans taux de TVA de
    reference.

autrement dit **le module Simulation ne pouvait construire aucun socle sur
aucune instance**. Le code etait juste ; rien ne l'amorcait. Meme patron que
le calendrier ferie (`load_mg_holidays`, ferme en L2-3) et que le
dictionnaire d'indicateurs (BI-1, encore ouvert).

**Pourquoi un parametre reglementaire ET une table `AccTax`.** Les deux ne
font pas le meme travail, et confondre les deux serait une erreur :

- `AccTax` est la verite TRANSACTIONNELLE. Elle porte le code, les comptes
  de TVA collectee et deductible, l'inclusion dans le prix, et c'est elle
  qu'un document reference. Une facture emise fige son taux (`tax_rate` sur
  la ligne) et ne le reinterprete jamais — discipline « document valide
  immuable » de tout ce depot.
- `tva.taux_normal` est la verite REGLEMENTAIRE : versionnee, datee, et
  surtout soumise au verrou de validation OECFM
  (`ACTIVE_CALCULATION_PARAMETER_CODES` +
  `check_regulatory_validation`). C'est ce verrou qui manquait : le taux de
  TVA etait le seul taux legal du produit a y echapper, alors que les dix
  parametres de paie y sont soumis depuis la Phase 3.

Ce module fournit la resolution reglementaire et la comparaison entre les
deux. Il ne remplace pas `AccTax` et ne reecrit aucun document.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.utils import timezone

from apps.accounting.models import AccTax
from apps.core.models.regulatory import RegulatoryParameter
from apps.core.models.tenant import Tenant
from apps.core.services.regulatory import get_parameter_with_version

# Le meme code que celui qu'`apps.simulation.services.baseline` attend
# depuis la Phase 1. Redeclare ici plutot qu'importe de `simulation` :
# `accounting` ne depend pas d'un module aval (regle de couplage n1), et
# c'est desormais `accounting` qui possede ce parametre.
VAT_STANDARD_RATE_CODE = "tva.taux_normal"


def resolve_reference_vat_rate(
    tenant: Tenant, *, at_date: dt.date | None = None
) -> tuple[Decimal, int] | None:
    """Taux de TVA de reference et version du parametre, A LA DATE DONNEE.

    `at_date` est la date du DOCUMENT, jamais « aujourd'hui » : un avoir
    emis en mars sur une facture de janvier doit retrouver le taux de
    janvier. C'est exactement ce que `get_parameter_with_version` sait
    faire, et la raison pour laquelle D9 l'exige ici.

    Renvoie `None` — jamais une exception — si aucun parametre n'est
    resolvable a cette date : un tenant peut legitimement n'avoir aucun
    referentiel de TVA (regime synthetique), et un appelant de lecture ne
    doit pas avoir a se proteger."""
    at_date = at_date or timezone.now().date()
    try:
        value, version = get_parameter_with_version(VAT_STANDARD_RATE_CODE, at_date, tenant)
    except RegulatoryParameter.DoesNotExist:
        return None
    rate = value["rate"] if isinstance(value, dict) else value
    return Decimal(str(rate)), version


def diverging_sale_taxes(
    tenant: Tenant, *, at_date: dt.date | None = None
) -> list[dict[str, object]]:
    """Taxes de vente du tenant dont le taux s'ecarte de la reference legale.

    LECTURE PURE, et volontairement pas une garde bloquante : un ecart peut
    etre parfaitement legitime (taux reduit sectoriel, exoneration), et
    refuser l'enregistrement casserait des cas reels. Ce que l'exploitant
    doit pouvoir faire, c'est le VOIR — un taux saisi a 18 % quand la loi
    dit 20 % est aujourd'hui indetectable autrement qu'a l'oeil.

    Renvoie une liste vide quand aucune reference n'est resolvable : sans
    reference, il n'y a pas d'ecart a constater, seulement une absence de
    point de comparaison."""
    at_date = at_date or timezone.now().date()
    reference = resolve_reference_vat_rate(tenant, at_date=at_date)
    if reference is None:
        return []
    reference_rate, reference_version = reference

    rows: list[dict[str, object]] = []
    for tax in AccTax.objects.filter(tenant=tenant, type=AccTax.TYPE_SALE):
        if tax.rate == reference_rate:
            continue
        rows.append(
            {
                "tax_id": str(tax.id),
                "code": tax.code,
                "name": tax.name,
                "rate": tax.rate,
                "reference_rate": reference_rate,
                "reference_version": reference_version,
            }
        )
    return rows
