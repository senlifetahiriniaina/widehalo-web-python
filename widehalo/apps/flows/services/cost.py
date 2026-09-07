"""Le compteur de cout transverse, et pourquoi il ne renvoie pas un nombre.

Decision structurante n°6 du cahier : « tout echange porte un cout impute
et un plafond opposable ». Le plafond a besoin d'un total ; ce module le
produit.

**Un total nu serait un piege, et c'est tout l'objet de l'hypothese H26.**
Le cahier prevoit que l'unite de cout de la messagerie puisse basculer — de
la conversation au message — avec, en repli, « deux unites qui coexistent,
avec une date de bascule ». Une somme sur une periode a cheval sur cette
bascule est exacte a l'ariary pres ET incomparable a la periode
precedente : ce ne sont pas les memes objets qu'on compte. Un nombre nu
laisserait cette incomparabilite invisible, et une jauge de plafond
afficherait une variation qui ne veut rien dire.

D'ou `CostTotal`, qui porte le montant ET les unites rencontrees. Un
appelant qui veut comparer deux periodes doit donc voir qu'elles ne sont
pas homogenes ; il ne peut pas l'ignorer par distraction.

**Ce que ce module ne fait pas : tarifer.** Aucune grille ici, aucun
montant en dur. « Les grilles tarifaires vivent dans les parametres
versionnes » (cahier §13.2), et le montant arrive deja impute sur la ligne
— c'est l'adaptateur qui applique la regle de son tiers. Sous facturation a
la conversation, c'est l'ouverture de la fenetre qui porte le prix et les
messages suivants portent zero ; sous facturation au message, chaque ligne
porte le sien. Dans les deux cas la somme est juste, et c'est pourquoi
l'unite qualifie le total sans changer son calcul.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db.models import Sum

from apps.flows.models import FlwExchange

if TYPE_CHECKING:
    import datetime as dt
    from uuid import UUID

    from apps.core.models.tenant import Tenant


@dataclass(frozen=True)
class CostTotal:
    """Un montant, et sous quelles unites il a ete constitue.

    `units` est vide quand aucun cout n'a encore ete impute sur la periode
    — ce qui n'est PAS la meme chose qu'un total de zero. Une periode sans
    echange et une periode dont les echanges n'ont pas encore ete tarifes
    valent toutes deux zero ariary et ne disent pas la meme chose : la
    seconde annonce une facture a venir."""

    amount: Decimal
    units: frozenset[str] = field(default_factory=frozenset)
    priced_rows: int = 0
    unpriced_rows: int = 0

    @property
    def is_homogeneous(self) -> bool:
        """Vrai si toutes les lignes tarifees relevent d'une seule unite.

        Une periode heterogene reste parfaitement TOTALISABLE — la somme
        est exacte. Ce qui devient faux, c'est la COMPARAISON avec une autre
        periode : on ne compare pas un nombre de conversations a un nombre
        de messages."""
        return len(self.units) <= 1

    @property
    def is_fully_priced(self) -> bool:
        """Faux tant qu'un echange de la periode n'a pas recu son cout. Un
        plafond evalue sur un total incomplet laisse passer des envois que
        le cout reel aurait bloques."""
        return self.unpriced_rows == 0


def cost_total(
    tenant: Tenant,
    *,
    since: dt.datetime,
    until: dt.datetime,
    link_id: UUID | None = None,
) -> CostTotal:
    """Le cout impute des echanges d'une periode, qualifie par ses unites.

    La periode porte sur `created_at` et non sur `sent_at` : un echange
    prepare puis jamais parti n'a rien coute, mais un echange parti le 1er
    d'un mois pour une piece du mois precedent appartient au mois ou il est
    PARTI. `created_at` et `sent_at` ne different que de la duree passee en
    file, et rattacher un cout au moment de la mise en file plutot qu'a
    celui de l'envoi ferait basculer d'un mois a l'autre les echanges
    retenus par un disjoncteur — c'est-a-dire ceux d'une panne."""
    queryset = FlwExchange.objects.filter(
        tenant=tenant,
        direction=FlwExchange.DIRECTION_OUTBOUND,
        created_at__gte=since,
        created_at__lt=until,
    )
    if link_id is not None:
        queryset = queryset.filter(link_id=link_id)

    priced = queryset.exclude(cost_ariary__isnull=True)
    amount = priced.aggregate(total=Sum("cost_ariary"))["total"] or Decimal(0)
    units = frozenset(priced.exclude(cost_unit="").values_list("cost_unit", flat=True).distinct())
    return CostTotal(
        amount=amount,
        units=units,
        priced_rows=priced.count(),
        unpriced_rows=queryset.filter(cost_ariary__isnull=True).count(),
    )


def compare_periods(current: CostTotal, previous: CostTotal) -> str:
    """Le motif qui INTERDIT la comparaison, ou une chaine vide.

    Renvoie un motif plutot qu'un booleen : l'appelant a besoin de
    l'afficher. « Comparaison impossible » sans raison est une impasse pour
    l'utilisateur, qui ne peut ni corriger ni comprendre.

    Chaine vide = comparaison licite. C'est le cas nominal, et il ne merite
    pas d'objet."""
    unites = current.units | previous.units
    if len(unites) > 1:
        return (
            "Les deux périodes ne relèvent pas de la même unité de coût "
            f"({', '.join(sorted(unites))}) : leurs montants sont exacts, mais "
            "les comparer reviendrait à comparer un nombre de conversations à un "
            "nombre de messages."
        )
    if not current.is_fully_priced or not previous.is_fully_priced:
        return (
            "Une des deux périodes contient des échanges dont le coût n'est pas "
            "encore imputé : la comparaison porterait sur un total incomplet."
        )
    return ""


__all__ = ["CostTotal", "compare_periods", "cost_total"]
