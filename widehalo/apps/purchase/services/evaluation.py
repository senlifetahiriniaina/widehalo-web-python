"""RG-PUR-8 (evaluation fournisseur, §5.6.2, PU7 du sous-sequencement
`purchase` — cf. plan) : mutualise entierement `MRP-QQCD1`
(`apps.mrp.models.MrpSupplierEvaluation`) via les 2 gaps ajoutes a
`apps.mrp.services.public` (`record_supplier_evaluation`/
`get_supplier_score`) — "une seule implementation, deux points d'entree",
aucun modele `PurSupplierEvaluation` cree dans ce module.

**Discipline "jamais de precision fabriquee"** (meme principe que A13/S6,
cf. plan) : la note ponderee QQCD (quantite/qualite/cout/delai/
conformite) exige 5 notes humaines — `purchase` n'a AUCUNE source de
donnee fiable pour automatiquement deriver les 5 (en particulier
qualite/cout, qui exigent un jugement humain sur la matiere/le prix
negocie). Ce fichier automatise UNIQUEMENT ce qui est honnetement
derivable des donnees deja tracees par `purchase` :

- `count_disputes_for_supplier` : nombre de `PurCri` ouverts sur un
  fournisseur dans une fenetre — indicateur objectif que l'evaluateur
  humain peut utiliser en entree de `score_delay`/`score_conformity`
  avant d'appeler `record_quarterly_evaluation`.
- `record_quarterly_evaluation` : wrapper mince qui resout `tenant`/
  `partner_id` et delegue integralement a
  `mrp.services.public.record_supplier_evaluation` — n'invente AUCUN
  score, les 5 notes restent des arguments obligatoires fournis par
  l'appelant (l'evaluateur humain, eventuellement aide par
  `count_disputes_for_supplier`)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from uuid import UUID

from apps.catalog.services.public import set_supplier_priority
from apps.core.models.tenant import Tenant
from apps.mrp.services.public import get_supplier_score, record_supplier_evaluation
from apps.purchase.models import PurCri

# RG-PUR-8 : `weighted_score` est deja une note ponderee sur 100 (verifie
# depuis `apps.mrp.services.suppliers.evaluate_supplier` : 5 notes /5 *
# poids en pourcentage, somme des poids par defaut = 100 => note maximale
# theorique = 5*100/5 = 100). Mapping documente ("plus bas = plus
# prioritaire", cf. `apps.catalog.models.ProductSupplierInfo.priority`) :
# `priority = max(1, 100 - int(score))`. Exemple verifie a la main :
# score=85.00 (tres bon fournisseur) => priority = max(1, 100-85) = 15
# (nombre bas = tres prioritaire) ; score=20.00 (mauvais fournisseur) =>
# priority = max(1, 100-20) = 80 (peu prioritaire) ; score=100.00 (note
# maximale theorique) => priority = max(1, 0) = 1 (le plancher, jamais
# 0 — `ProductSupplierInfo.priority` est un `PositiveSmallIntegerField`,
# et `0` romprait la lisibilite du rang "1 = le plus prioritaire").
MAX_SCORE = Decimal(100)


def count_disputes_for_supplier(
    partner_id: UUID, *, period_start: dt.date, period_end: dt.date
) -> int:
    """Nombre de `PurCri` (tous types confondus) ouverts pour ce
    fournisseur entre `period_start` et `period_end` inclus — indicateur
    objectif brut, jamais une note en soi (l'evaluateur humain en tire ce
    qu'il veut pour `score_delay`/`score_conformity`)."""
    return PurCri.objects.filter(
        partner_id=partner_id, date__gte=period_start, date__lte=period_end
    ).count()


def record_quarterly_evaluation(
    *,
    tenant: Tenant,
    partner_id: UUID,
    period_start: dt.date,
    period_end: dt.date,
    score_quantity: Decimal,
    score_quality: Decimal,
    score_cost: Decimal,
    score_delay: Decimal,
    score_conformity: Decimal,
    weights: dict[str, int] | None = None,
    conformity_blocking: bool = False,
    notes: str = "",
) -> UUID:
    """Wrapper mince RG-PUR-8 : `period_start`/`period_end` ne sont PAS
    persistes tels quels (`MrpSupplierEvaluation` ne porte qu'un `date`
    unique, pas de bornes de periode — champ non etendu ici pour rester
    strictement dans le gap deja mutualise) — `period_end` est retenu comme
    `date` de l'evaluation (date de cloture de la periode evaluee, la plus
    parlante pour un releve trimestriel). Les 5 notes restent des
    arguments obligatoires (cf. docstring de ce module) : AUCUN calcul
    automatique de score ici, uniquement une resolution
    `tenant`/`partner_id` et une delegation integrale a
    `mrp.services.public.record_supplier_evaluation`."""
    return record_supplier_evaluation(
        tenant=tenant,
        partner_id=partner_id,
        date=period_end,
        score_quantity=score_quantity,
        score_quality=score_quality,
        score_cost=score_cost,
        score_delay=score_delay,
        score_conformity=score_conformity,
        weights=weights,
        conformity_blocking=conformity_blocking,
        notes=notes,
    )


def apply_score_to_priority(partner_id: UUID, *, variant_ids: list[UUID] | None = None) -> int:
    """RG-PUR-8 : "le score influe sur `priority`" — recalcule
    `ProductSupplierInfo.priority` (via le gap
    `catalog.services.public.set_supplier_priority`, `purchase` ne
    manipule jamais `ProductSupplierInfo` directement) a partir du dernier
    score connu de ce fournisseur (`get_supplier_score`, cf. sa docstring
    pour le choix "plus recente evaluation").

    Mapping documente en tete de module : `priority = max(1, 100 -
    int(score))`. Retourne le nombre de lignes `ProductSupplierInfo` mises
    a jour ; retourne `0`, JAMAIS une exception, si le fournisseur n'a
    encore aucune evaluation (`get_supplier_score` renvoie `None`) — rien
    a appliquer, pas une erreur."""
    score = get_supplier_score(partner_id)
    if score is None:
        return 0

    priority = max(1, int(MAX_SCORE - score))
    return set_supplier_priority(partner_id, priority=priority, variant_ids=variant_ids)
