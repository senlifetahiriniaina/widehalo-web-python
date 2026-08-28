"""Classification ABC et comptage cyclique (§5.8, ST5 du sous-sequencement
`stocks` — cf. plan) : STK-ABC1 — classement periodique des produits par
valeur de consommation (methode de Pareto/80-15-5, convention classique de
gestion des stocks) ; STK-CYCLE1 — cadence de comptage cyclique deduite de
la classe (A mensuel, B trimestriel, C annuel).

**Consommation retenue** : somme de `StkMove.value_mga` des mouvements
`done` de type `livraison` (sortie client) ou `production_out` (sortie
consommee en production) sur la fenetre `[as_of - period_days, as_of]` —
ce sont les 2 seuls `StkMove.MOVE_TYPE_CHOICES` qui representent une
consommation REELLE du stock au sens ABC (une livraison client ou une
consommation de production), a l'exclusion des transferts internes/
receptions/retours/rebuts/ajustements qui ne mesurent aucune "demande"
recurrente sur le produit.

**Cutoffs Pareto assumes (80/15/5 cumules)** : le CDC (STK-ABC1) ne fixe
aucun pourcentage precis — 80/15/5 (cumulatif : A jusqu'a 80% de la valeur
cumulee, B jusqu'a 95%, C au-dela) est la convention ABC standard la plus
largement citee en gestion des stocks (regle empirique "20% des references
representent 80% de la valeur"), retenue ici comme defaut assume plutot
qu'une repartition inventee sans reference. Classement par produit
(variant_id), pas par ligne de mouvement individuelle.

**Cadence de comptage cyclique (STK-CYCLE1)** : le CDC precise "A mensuel,
B trimestriel, C annuel" sans jour exact — decalages retenus ici :
A = +30 jours, B = +90 jours, C = +365 jours a partir de `computed_at`,
les approximations calendaires les plus simples et les plus lisibles pour
ces 3 cadences (mois/trimestre/annee), meme discipline "documenter les
defauts assumes" que le reste de ce sous-sequencement."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.stocks.models import StkAbcClassification, StkMove

# STK-ABC1 : cutoffs cumules assumes (cf. docstring de module).
_CUTOFF_A_PCT = Decimal("80")
_CUTOFF_B_PCT = Decimal("95")

# STK-CYCLE1 : cadence de comptage cyclique par classe (cf. docstring de
# module).
_CADENCE_DAYS: dict[str, int] = {
    StkAbcClassification.CLASS_A: 30,
    StkAbcClassification.CLASS_B: 90,
    StkAbcClassification.CLASS_C: 365,
}

# Types de mouvement consideres comme "consommation reelle" au sens ABC
# (cf. docstring de module).
_CONSUMPTION_MOVE_TYPES = (StkMove.TYPE_LIVRAISON, StkMove.TYPE_PRODUCTION_OUT)


def _classify(cumulative_pct: Decimal) -> str:
    if cumulative_pct <= _CUTOFF_A_PCT:
        return StkAbcClassification.CLASS_A
    if cumulative_pct <= _CUTOFF_B_PCT:
        return StkAbcClassification.CLASS_B
    return StkAbcClassification.CLASS_C


def compute_abc_classification(
    tenant: Tenant, *, as_of: dt.date | None = None, period_days: int = 90
) -> list[StkAbcClassification]:
    """Recalcule (`update_or_create`, une ligne PAR produit) la
    classification ABC de tous les produits ayant eu au moins un
    mouvement de consommation sur la fenetre retenue, classes par valeur
    de consommation DECROISSANTE avant application des cutoffs cumules
    (STK-ABC1). Un produit sans aucun mouvement de consommation sur la
    fenetre n'apparait PAS dans le resultat (rien a classer — sa
    classification precedente, si elle existe, reste inchangee plutot que
    supprimee : une classification est une photo de la derniere fenetre
    CALCULEE, pas une garantie de couverture exhaustive du catalogue a
    chaque appel)."""
    as_of = as_of or timezone.now().date()
    window_start = as_of - dt.timedelta(days=period_days)

    rows = list(
        StkMove.objects.filter(
            tenant=tenant,
            state=StkMove.STATE_DONE,
            move_type__in=_CONSUMPTION_MOVE_TYPES,
            date__gte=window_start,
            date__lte=as_of,
        )
        .values("variant_id")
        .annotate(total_value=Sum("value_mga"))
        .order_by("-total_value")
    )

    total_value = sum((row["total_value"] or Decimal(0)) for row in rows) or Decimal(0)
    now = timezone.now()
    results: list[StkAbcClassification] = []
    cumulative_value = Decimal(0)
    for row in rows:
        value = row["total_value"] or Decimal(0)
        cumulative_value += value
        cumulative_pct = (cumulative_value / total_value * 100) if total_value > 0 else Decimal(100)
        abc_class = _classify(cumulative_pct)
        next_count_due = as_of + dt.timedelta(days=_CADENCE_DAYS[abc_class])
        classification, _created = StkAbcClassification.objects.update_or_create(
            tenant=tenant,
            variant_id=row["variant_id"],
            defaults={
                "abc_class": abc_class,
                "consumption_value_mga": value,
                "computed_at": now,
                "next_count_due": next_count_due,
            },
        )
        results.append(classification)
    return results


def due_cyclic_counts(
    tenant: Tenant, *, as_of: dt.date | None = None
) -> list[StkAbcClassification]:
    """STK-CYCLE1 : liste des classifications dont le comptage cyclique
    est du (`next_count_due <= as_of`, aujourd'hui par defaut) — la liste
    qu'un ecran de comptage tournant (ST7/ST8, hors perimetre ST5)
    consommerait pour savoir quoi compter aujourd'hui. Ne cree AUCUN
    `StkInventory` elle-meme — c'est une decision humaine/ops, meme
    discipline "pas de creation automatique" que le reste de ce
    sous-sequencement."""
    as_of = as_of or timezone.now().date()
    return list(
        StkAbcClassification.objects.filter(tenant=tenant, next_count_due__lte=as_of).order_by(
            "next_count_due"
        )
    )
