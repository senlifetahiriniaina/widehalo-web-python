"""T9 (CON-5, §15.2) — le plafond opposable d'une liaison, et son alerte
avant l'atteinte.

**Ce que la mesure a trouve avant qu'une ligne soit ecrite.** Tout etait
la, sauf le plafond :

- `cost.py::cost_total` calcule le total impute d'une periode — et n'avait
  **aucun appelant de production** ;
- `FlwExchange.STATE_SUSPENDED` existe dans la machine a etats, avec son
  invariant ecrit (« un plafond atteint n'ouvre pas d'incident : ce n'est
  pas une panne, c'est une decision ») et les deux transitions qu'il faut,
  `EN_FILE → SUSPENDU` et `SUSPENDU → EN_FILE` (« le plafond est releve ou
  le mois change : l'echange repart ») — et **rien ne l'ecrivait** ;
- `incidents.py` propose comme action de reprise « relever le plafond de la
  liaison » — pour un plafond qui n'etait un champ nulle part.

Un compteur, un etat et une action de reprise, ecrits, documentes,
coherents entre eux, et aucun des trois branche. Ce module est ce qui les
relie.

**Le budget se calcule UNE FOIS par passe et par liaison.** Interroger
`cost_total` a chaque echange rendrait la vidange quadratique — le defaut
paye deux fois deja dans ce depot (le rapprochement de T3, les candidats de
relevé de T6). Le total de depart est donc lu une fois, puis le cout impute
pendant la passe s'y ajoute au fur et a mesure : exact, et une requete par
liaison.

**Un total incomplet ne bloque pas tout, et ce n'est pas une facilite.**
`CostTotal.is_fully_priced` distingue « rien n'a coute » de « rien n'a
encore ete tarife », et sa docstring avertit qu'« un plafond evalue sur un total
incomplet laisse passer des envois que le cout reel aurait bloques ». C'est
vrai, et l'inverse serait pire : suspendre toute une liaison parce qu'un
adaptateur n'a pas encore impute son cout ferait d'un retard de tarification
une panne d'exploitation. Le total connu est donc une BORNE INFERIEURE, on
oppose ce qu'on sait, et l'incompletude remonte a la jauge pour que
l'exploitant la voie au lieu de la subir.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from django.utils import timezone

from apps.flows.services.cost import cost_total

if TYPE_CHECKING:
    from apps.flows.models import FlwLink


def month_bounds(moment: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    """Le mois calendaire qui contient `moment`, borne a gauche, ouvert a
    droite.

    Le mois CALENDAIRE et non une fenetre glissante de trente jours : le
    §15.2 parle d'une « restitution mensuelle », et une facture de tiers se
    lit par mois. Une fenetre glissante rendrait la jauge irreconciliable
    avec la facture qu'elle est censee expliquer."""
    debut = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if debut.month == 12:
        fin = debut.replace(year=debut.year + 1, month=1)
    else:
        fin = debut.replace(month=debut.month + 1)
    return debut, fin


@dataclass
class CapBudget:
    """Ce qui reste a depenser sur une liaison ce mois-ci.

    Mutable a dessein : la passe de vidange l'impute au fur et a mesure
    plutot que de relire le total a chaque echange."""

    cap: Decimal | None
    spent: Decimal
    threshold_pct: int
    complete: bool
    already_alerted: bool

    @property
    def is_capped(self) -> bool:
        """`None` signifie « aucun plafond configure », jamais « plafond a
        zero » — un plafond implicite a zero bloquerait tout envoi des la
        premiere liaison creee."""
        return self.cap is not None

    @property
    def reached(self) -> bool:
        return self.is_capped and self.spent >= self.cap  # type: ignore[operator]

    @property
    def approaching(self) -> bool:
        """Au-dela du seuil, mais pas encore atteint. **C'est le mot
        « avant » du critere CON-5** : « une alerte est emise a l'approche
        d'un plafond, AVANT son atteinte ». Alerter a 100 % tiendrait le mot
        « alerte » et manquerait le critere."""
        if not self.is_capped or self.reached:
            return False
        seuil = self.cap * Decimal(self.threshold_pct) / Decimal(100)  # type: ignore[operator]
        return self.spent >= seuil

    @property
    def ratio_pct(self) -> int:
        """Pour la jauge. Zero quand il n'y a pas de plafond : afficher
        « 0 % » d'un plafond inexistant serait moins trompeur qu'une barre
        pleine, et l'ecran dit de toute facon « aucun plafond »."""
        if not self.is_capped or self.cap == 0:
            return 0
        return int(self.spent * 100 / self.cap)  # type: ignore[operator]

    def charge(self, amount: Decimal | None) -> None:
        """Impute un cout survenu pendant la passe en cours."""
        if amount is not None:
            self.spent += amount


def budget_for(link: FlwLink, *, now: dt.datetime | None = None) -> CapBudget:
    """Lit le budget du mois courant pour cette liaison. UNE fois par passe."""
    moment = now or timezone.now()
    debut, fin = month_bounds(moment)
    total = cost_total(link.tenant, since=debut, until=fin, link_id=link.id)
    return CapBudget(
        cap=link.monthly_cost_cap_ariary,
        spent=total.amount,
        threshold_pct=link.cost_alert_threshold_pct,
        complete=total.is_fully_priced,
        already_alerted=link.cost_alerted_for_month == debut.date(),
    )


def mark_alerted(link: FlwLink, *, now: dt.datetime | None = None) -> None:
    """Retient qu'on a deja averti pour ce mois.

    Sans cette marque, chaque echange au-dela du seuil realerterait. Le
    §10.1 refuse qu'un avertissement devienne du bruit : « un plafond
    atteint un 28 du mois sans avertissement est vecu comme une panne » —
    mais trente avertissements pour le meme plafond le sont tout autant, et
    le trente-et-unieme ne sera plus lu."""
    debut, _fin = month_bounds(now or timezone.now())
    link.cost_alerted_for_month = debut.date()
    link.save(update_fields=["cost_alerted_for_month"])


__all__ = ["CapBudget", "budget_for", "mark_alerted", "month_bounds"]
