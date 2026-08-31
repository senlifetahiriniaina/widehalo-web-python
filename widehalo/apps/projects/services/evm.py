"""Service EVM (Earned Value Management, PJ4) : SPI/CPI/EAC + courbe en S
CAPEX/OPEX — cf. plan, section « Module `projects` », etape PJ4.
Differenciateur documente au plan comme absent d'Asana/Monday/Jira/
ClickUp.

**Methode PV/EV retenue (V1), disclosee explicitement plutot qu'une fausse
precision** — meme discipline de disclosure que partout ailleurs dans ce
projet (ex. ACC-CF methode directe vs indirecte) :

1. **PV (Planned Value)** : repartition LINEAIRE du budget total planifie
   (`BAC`) sur la duree calendaire du projet entre `PrjProject.start_date`
   et `PrjProject.end_date` — PAS une derivation depuis un planning detaille
   tache par tache (ce qui exigerait un pourcentage d'avancement PLANIFIE
   par tache, absent du modele `PrjTask` actuel qui ne porte que
   `percent_complete` REEL). `PV(as_of) = BAC * clamp((as_of - start_date)
   / (end_date - start_date), 0, 1)`. **Non calculable** (renvoie `None`) si
   le projet n'a pas les deux dates renseignees — jamais une date inventee.
2. **EV (Earned Value)** : `EV = BAC * avancement_moyen_pondere_du_projet`,
   ou l'avancement moyen pondere est la moyenne des `PrjTask.
   percent_complete` de TOUTES les taches actives du projet (y compris
   celles `cancelled` — pas d'exclusion de state en V1, limite disclosee),
   ponderee par `duration_days` de chaque tache (bascule sur une moyenne
   simple non ponderee si la somme des durees est nulle — ex. taches sans
   duree renseignee). **Non calculable** (renvoie `None`) si le projet n'a
   aucune tache active (moyenne indefinie sur un ensemble vide).
3. **AC (Actual Cost)** = somme de `PrjBudgetLine.actual_amount` du projet
   (toujours calculable, `0` si aucune ligne de cout reel).
4. **BAC (Budget At Completion)** = somme de `PrjBudgetLine.planned_amount`
   du projet (toujours calculable, `0` si aucune ligne budgetaire).
5. **SPI = EV / PV**, **CPI = EV / AC** — `None` si le numerateur (`EV`) ou
   le denominateur est `None` OU nul (division par zero -> `None`, jamais
   une `ZeroDivisionError` ni une valeur inventee, meme patron deja
   applique par `apps.accounting.services.budgets._ratio_or_none` et les
   ratios financiers de `apps.strategy`).
6. **EAC (Estimate At Completion)** : methode "CPI applique au reste a
   faire" (la plus courante parmi les variantes EAC connues) :
   `EAC = AC + (BAC - EV) / CPI`. D'autres variantes existent (ex.
   `EAC = AC + (BAC - EV)` en supposant que les ecarts futurs seront
   corriges — methode "reste au budget" ; ou `EAC = BAC / CPI` en
   supposant une performance de cout constante sur tout le projet) —
   **methode retenue disclosee explicitement ici**, coherente avec le
   principe deja applique ailleurs dans ce projet (ex. ACC-CF, methode
   directe vs indirecte, disclosee comme un choix legitime parmi
   plusieurs). `None` si `CPI` est `None` ou nul.

Tous les montants/ratios sont des `Decimal` (jamais `float`), quantifies a
4 decimales (`_MONEY_QUANT`) pour les montants et 4 decimales pour les
ratios — coherent avec la precision `DecimalField(18, 4)` du modele
`PrjBudgetLine`.

**Seuils de statut projet (`PrjProject.status`), politique V1 disclosee
— PAS une norme externe** :
- `on_track` si `SPI >= 0.95` ET `CPI >= 0.95` (le projet n'accuse pas de
  retard/depassement significatif sur l'un ou l'autre axe) ;
- `off_track` si `SPI < 0.85` OU `CPI < 0.85` (retard/depassement marque
  sur au moins un axe) ;
- `at_risk` dans tous les autres cas (l'un des deux indicateurs est dans
  la zone intermediaire [0.85, 0.95[, sans que l'autre ne soit critique) ;
- si `SPI`/`CPI` ne sont pas calculables (`None`), le statut n'est PAS
  modifie (le champ garde sa valeur courante) — pas de valeur inventee en
  l'absence de donnees suffisantes (projet qui vient de demarrer, aucune
  ligne budgetaire ou aucune tache active).

**Courbe en S CAPEX/OPEX** (`compute_s_curve`) : serie temporelle des
montants CUMULES planifies/reels de `PrjBudgetLine`, ventiles par
`category`, groupes par mois calendaire (`period` normalise au 1er jour du
mois — seule granularite prise en charge en V1, `granularity="monthly"`).
**Simplification V1 disclosee** : seuls les mois pour lesquels au moins
une ligne budgetaire existe apparaissent dans la serie — pas de
remplissage/interpolation des mois sans ligne (pas de "mois vide a 0"
artificiel entre deux mois avec donnees). Structure de chaque point,
exploitable directement par un futur graphique (report PDF/ecran, cf.
PJ15) : `{"period": "AAAA-MM-01", "capex_planned_cumulative": Decimal,
"capex_actual_cumulative": Decimal, "opex_planned_cumulative": Decimal,
"opex_actual_cumulative": Decimal}`. **Le rendu graphique reel de cette
courbe (SVG/JS) n'est PAS construit** — simplification V1 assumee et
definitivement close a PJ15 (chantier termine, cf. plan) : l'ecran HTMX de
PJ4 affiche cette serie sous forme de simple tableau de valeurs, et le
catalogue de rapports PJ15 (`services/reports_registration.py`) ne
l'expose pas non plus — un futur graphique resterait un candidat naturel
d'evolution HORS de ce chantier, `compute_s_curve` restant disponible tel
quel comme source de donnees."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.projects.models import PrjBudgetLine, PrjProject

_MONEY_QUANT = Decimal("0.0001")
_RATIO_QUANT = Decimal("0.0001")

_STATUS_ON_TRACK_THRESHOLD = Decimal("0.95")
_STATUS_OFF_TRACK_THRESHOLD = Decimal("0.85")


@dataclass(frozen=True)
class EVMSnapshot:
    """Photo instantanee des indicateurs EVM d'un projet a une date donnee
    (`as_of`, par defaut aujourd'hui). Tous les champs sont `Decimal | None`
    — `None` signifie explicitement "non calculable avec les donnees
    actuelles", jamais une valeur inventee (0 est une valeur legitime
    distincte de `None`, ex. `ac=0` quand aucun cout reel n'a encore ete
    constate)."""

    pv: Decimal | None
    ev: Decimal | None
    ac: Decimal | None
    bac: Decimal | None
    spi: Decimal | None
    cpi: Decimal | None
    eac: Decimal | None


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY_QUANT)


def _ratio_or_none(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    """Meme patron que `apps.accounting.services.budgets._ratio_or_none` :
    `None` sur numerateur absent ou denominateur nul/absent, jamais une
    `ZeroDivisionError` ni une valeur inventee."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return (numerator / denominator).quantize(_RATIO_QUANT)


def _compute_bac_ac(project: PrjProject) -> tuple[Decimal, Decimal]:
    lines = PrjBudgetLine.objects.filter(project=project, is_active=True)
    totals = lines.aggregate(bac=Sum("planned_amount"), ac=Sum("actual_amount"))
    bac = totals["bac"] if totals["bac"] is not None else Decimal("0")
    ac = totals["ac"] if totals["ac"] is not None else Decimal("0")
    return _quantize_money(bac), _quantize_money(ac)


def _compute_pv(project: PrjProject, bac: Decimal, as_of: dt.date) -> Decimal | None:
    """Cf. docstring de module, point 1 — repartition lineaire du BAC sur
    la duree calendaire du projet, `None` si les deux dates ne sont pas
    renseignees."""
    if project.start_date is None or project.end_date is None:
        return None
    total_days = (project.end_date - project.start_date).days
    if total_days <= 0:
        # Projet a duree nulle/negative (dates incoherentes) : tout le
        # budget est repute planifie des le premier jour.
        return bac
    elapsed_days = (as_of - project.start_date).days
    elapsed_days = max(0, min(elapsed_days, total_days))
    fraction = Decimal(elapsed_days) / Decimal(total_days)
    return _quantize_money(bac * fraction)


def _compute_ev(project: PrjProject, bac: Decimal) -> Decimal | None:
    """Cf. docstring de module, point 2 — moyenne ponderee (par
    `duration_days`, ou simple moyenne si toutes les durees sont nulles)
    de `percent_complete` sur les taches actives du projet, `None` si
    aucune tache active n'existe."""
    tasks = list(project.tasks.filter(is_active=True).values("percent_complete", "duration_days"))
    if not tasks:
        return None
    total_weight = sum(t["duration_days"] for t in tasks)
    if total_weight > 0:
        weighted_sum = sum(t["percent_complete"] * t["duration_days"] for t in tasks)
        avg_fraction = Decimal(weighted_sum) / Decimal(total_weight) / Decimal(100)
    else:
        avg_fraction = (
            Decimal(sum(t["percent_complete"] for t in tasks)) / Decimal(len(tasks)) / Decimal(100)
        )
    return _quantize_money(bac * avg_fraction)


def compute_evm_snapshot(project: PrjProject, *, as_of: dt.date | None = None) -> EVMSnapshot:
    """Calcule l'instantane EVM du projet a la date `as_of` (aujourd'hui
    par defaut). Fonction pure — aucune ecriture en base (cf.
    `refresh_project_health` pour la mise a jour persistee de
    `PrjProject.status`)."""
    as_of = as_of or timezone.now().date()
    bac, ac = _compute_bac_ac(project)
    pv = _compute_pv(project, bac, as_of)
    ev = _compute_ev(project, bac)
    spi = _ratio_or_none(ev, pv)
    cpi = _ratio_or_none(ev, ac)
    eac: Decimal | None = None
    if cpi is not None and cpi != 0 and ev is not None:
        eac = _quantize_money(ac + (bac - ev) / cpi)
    return EVMSnapshot(pv=pv, ev=ev, ac=ac, bac=bac, spi=spi, cpi=cpi, eac=eac)


def compute_project_health(spi: Decimal | None, cpi: Decimal | None) -> str | None:
    """Politique de seuils V1 (disclosee dans la docstring de module) —
    `None` si `SPI`/`CPI` ne sont pas tous les deux calculables (pas de
    statut invente en l'absence de donnees suffisantes)."""
    if spi is None or cpi is None:
        return None
    if spi < _STATUS_OFF_TRACK_THRESHOLD or cpi < _STATUS_OFF_TRACK_THRESHOLD:
        return PrjProject.STATUS_OFF_TRACK
    if spi >= _STATUS_ON_TRACK_THRESHOLD and cpi >= _STATUS_ON_TRACK_THRESHOLD:
        return PrjProject.STATUS_ON_TRACK
    return PrjProject.STATUS_AT_RISK


def refresh_project_health(project: PrjProject, *, as_of: dt.date | None = None) -> EVMSnapshot:
    """Calcule l'instantane EVM puis met a jour `PrjProject.status` selon
    la politique de seuils de `compute_project_health` — SEULE fonction du
    module qui ecrit en base. Si le statut n'est pas calculable (`SPI`/
    `CPI` absents), `PrjProject.status` n'est PAS modifie (cf. docstring de
    module)."""
    snapshot = compute_evm_snapshot(project, as_of=as_of)
    status = compute_project_health(snapshot.spi, snapshot.cpi)
    if status is not None and status != project.status:
        project.status = status
        project.save(update_fields=["status"])
    return snapshot


def add_budget_line(
    project: PrjProject,
    *,
    category: str,
    label: str,
    planned_amount: Decimal,
    period: dt.date,
    actual_amount: Decimal = Decimal("0"),
) -> PrjBudgetLine:
    """Cree une ligne budgetaire projet. Refuse explicitement (jamais une
    creation silencieuse) une categorie inconnue ou un montant planifie
    negatif — les montants reels negatifs (avoirs/corrections) restent
    autorises, meme discipline que le reste de la comptabilite analytique
    de ce projet."""
    valid_categories = {choice[0] for choice in PrjBudgetLine.CATEGORY_CHOICES}
    if category not in valid_categories:
        raise ValidationError(_("Catégorie de ligne budgétaire inconnue."))
    if planned_amount < 0:
        raise ValidationError(_("Le montant planifie ne peut pas être négatif."))
    return PrjBudgetLine.objects.create(
        tenant=project.tenant,
        project=project,
        category=category,
        label=label,
        planned_amount=planned_amount,
        actual_amount=actual_amount,
        period=period,
    )


def compute_s_curve(project: PrjProject, *, granularity: str = "monthly") -> list[dict[str, Any]]:
    """Cf. docstring de module — courbe en S CAPEX/OPEX cumulee, seule
    granularite `"monthly"` prise en charge en V1."""
    if granularity != "monthly":
        raise ValidationError(
            _("Seule la granularite 'monthly' est prise en charge en V1 de la courbe en S.")
        )
    lines = PrjBudgetLine.objects.filter(project=project, is_active=True).order_by("period")

    planned_by_month: dict[dt.date, dict[str, Decimal]] = defaultdict(
        lambda: {
            PrjBudgetLine.CATEGORY_CAPEX: Decimal("0"),
            PrjBudgetLine.CATEGORY_OPEX: Decimal("0"),
        }
    )
    actual_by_month: dict[dt.date, dict[str, Decimal]] = defaultdict(
        lambda: {
            PrjBudgetLine.CATEGORY_CAPEX: Decimal("0"),
            PrjBudgetLine.CATEGORY_OPEX: Decimal("0"),
        }
    )
    for line in lines:
        month = line.period.replace(day=1)
        planned_by_month[month][line.category] += line.planned_amount
        actual_by_month[month][line.category] += line.actual_amount

    months = sorted(set(planned_by_month) | set(actual_by_month))
    cum_capex_planned = Decimal("0")
    cum_opex_planned = Decimal("0")
    cum_capex_actual = Decimal("0")
    cum_opex_actual = Decimal("0")
    points: list[dict[str, Any]] = []
    for month in months:
        cum_capex_planned += planned_by_month[month][PrjBudgetLine.CATEGORY_CAPEX]
        cum_opex_planned += planned_by_month[month][PrjBudgetLine.CATEGORY_OPEX]
        cum_capex_actual += actual_by_month[month][PrjBudgetLine.CATEGORY_CAPEX]
        cum_opex_actual += actual_by_month[month][PrjBudgetLine.CATEGORY_OPEX]
        points.append(
            {
                "period": month.isoformat(),
                "capex_planned_cumulative": _quantize_money(cum_capex_planned),
                "capex_actual_cumulative": _quantize_money(cum_capex_actual),
                "opex_planned_cumulative": _quantize_money(cum_opex_planned),
                "opex_actual_cumulative": _quantize_money(cum_opex_actual),
            }
        )
    return points
