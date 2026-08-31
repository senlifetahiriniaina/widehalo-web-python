"""Capacite de charge a 90 jours (CAP1-2, cf. plan) : service de CALCUL
pur (rapport) + notification — AUCUN nouveau modele. Toute decision
d'ajustement prise avec les decideurs se consigne en creant un
`apps.strategy.models.StgNote` existant (via l'API/l'ecran, pas ici), et
le rapport tabulaire `CAP-90J` est enregistre dans le catalogue
`reporting` (cf. `services/reports_registration.py`).

**Sources agregees, toutes via `services.public` (regle de couplage
n°1 — `strategy` n'importe jamais un modele d'une autre app)** :
- `mrp.services.public.get_total_workshop_capacity` : capacite BRUTE en
  heures/jour, tous ateliers non sous-traitants confondus (cf. sa
  docstring — pas une quantite de produits servables).
- `mrp.services.public.list_planned_orders_workload` : ordres `MrpOrder`
  planifies dans l'horizon avec une estimation d'heures de charge (gap
  ajoute par ce chantier, cf. `apps/mrp/services/public.py`).
- `presence.services.public.get_tenant_absence_days_in_period` : volume
  d'absences validees tenant-wide sur chaque semaine (gap ajoute par ce
  chantier) — indicateur INFORMATIF affiche a cote de la charge/capacite,
  jamais utilise pour recalculer une capacite ajustee en heures (convertir
  un jour-personne absent en heures-atelier perdues demanderait une regle
  de correspondance effectif <-> atelier hors perimetre de ce lot, cf.
  limite documentee de `get_total_workshop_capacity`).
- `payroll.services.public.get_payroll_mass_projection` : projection de
  masse salariale sur les mois couverts par l'horizon (meme fonction que
  celle deja consommee par le rapport business plan `STRATEGY-BP`).

**Structure retenue pour le tableau croise (documentee, "libre" au sens du
plan)** : une ligne par semaine glissante de 7 jours a partir d'aujourd'hui
(la derniere semaine peut etre partielle si `horizon_days` n'est pas un
multiple de 7), avec pour chaque semaine : capacite disponible (heures),
charge planifiee (heures), taux de charge (%), nombre d'ordres, et volume
d'absences (jours-personne, informatif). Une semaine (et non un atelier)
est retenue comme granularite de ligne car `get_total_workshop_capacity`
n'expose qu'un total agrege tous ateliers confondus (aucune ventilation
par atelier disponible sans un gap supplementaire hors perimetre de ce
chantier) — dette mineure disclosed, une evolution future pourrait
ventiler par atelier si `mrp` expose un jour une capacite par atelier.

**Seuil de notification** : `DEFAULT_OVERLOAD_THRESHOLD_PCT = Decimal("90")`
— une semaine dont la charge planifiee depasse 90% de la capacite
disponible declenche une notification `direction` + `resp_production`
(ajustement semi-automatique avec les decideurs, cf. plan). Seuil
parametrable via l'argument `overload_threshold_pct` de
`build_capacity_outlook`."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.utils.translation import gettext as _

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant

DEFAULT_OVERLOAD_THRESHOLD_PCT = Decimal("90")
DEFAULT_HORIZON_DAYS = 90
_WEEK_DAYS = 7


def _week_windows(*, start: dt.date, horizon_days: int) -> list[tuple[dt.date, dt.date]]:
    """Decoupe `[start, start + horizon_days]` en fenetres de 7 jours,
    la derniere pouvant etre partielle (ex. horizon_days=90 -> 12 semaines
    completes + 6 jours)."""
    windows: list[tuple[dt.date, dt.date]] = []
    offset = 0
    while offset < horizon_days:
        week_start = start + dt.timedelta(days=offset)
        week_end = min(
            start + dt.timedelta(days=offset + _WEEK_DAYS - 1),
            start + dt.timedelta(days=horizon_days),
        )
        windows.append((week_start, week_end))
        offset += _WEEK_DAYS
    return windows


def build_capacity_outlook(
    tenant: Tenant,
    *,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    overload_threshold_pct: Decimal = DEFAULT_OVERLOAD_THRESHOLD_PCT,
    today: dt.date | None = None,
    notify: bool = True,
) -> dict[str, Any]:
    """Construit le tableau capacite-vs-charge sur `horizon_days` jours
    (90 par defaut) et notifie `direction`/`resp_production` pour toute
    semaine en surcharge (> `overload_threshold_pct`).

    `today` : injectable pour les tests (deterministe), sinon
    `dt.date.today()`. `notify=False` permet un calcul "a blanc" (ex.
    previsualisation ecran) sans declencher de notification a chaque
    rafraichissement — seule la generation du rapport `CAP-90J`/l'appel
    explicite depuis un ecran de decision doit notifier.

    Retourne un dict `{horizon_days, generated_on, overload_threshold_pct,
    weeks: [...], payroll_projection: [...], overloaded_week_starts: [...]}`
    — primitives uniquement (`Decimal`/`str`/`date`), jamais un objet
    metier d'un autre module (regle de couplage n°1)."""
    from apps.mrp.services.public import (
        get_total_workshop_capacity,
        list_planned_orders_workload,
    )
    from apps.payroll.services.public import get_payroll_mass_projection
    from apps.presence.services.public import get_tenant_absence_days_in_period

    today = today or dt.date.today()
    daily_capacity_hours = get_total_workshop_capacity(tenant)
    planned_orders = list_planned_orders_workload(tenant, horizon_days=horizon_days)

    weeks: list[dict[str, Any]] = []
    overloaded_week_starts: list[dt.date] = []
    for index, (week_start, week_end) in enumerate(
        _week_windows(start=today, horizon_days=horizon_days), start=1
    ):
        nb_days = (week_end - week_start).days + 1
        capacity_hours = daily_capacity_hours * Decimal(nb_days)
        week_orders = [
            order
            for order in planned_orders
            if week_start <= order["date_planned_start"] <= week_end
        ]
        planned_workload_hours = sum(
            (order["estimated_hours"] for order in week_orders), start=Decimal(0)
        )
        workload_pct = (
            (planned_workload_hours / capacity_hours * Decimal(100))
            if capacity_hours > 0
            else Decimal(0)
        )
        absence_days = get_tenant_absence_days_in_period(
            tenant, date_from=week_start, date_to=week_end
        )
        is_overloaded = capacity_hours > 0 and workload_pct > overload_threshold_pct
        if is_overloaded:
            overloaded_week_starts.append(week_start)
        weeks.append(
            {
                "week_index": index,
                "week_start": week_start,
                "week_end": week_end,
                "capacity_hours": capacity_hours,
                "planned_workload_hours": planned_workload_hours,
                "workload_pct": workload_pct.quantize(Decimal("0.01")),
                "orders_count": len(week_orders),
                "absence_days": absence_days,
                "is_overloaded": is_overloaded,
            }
        )

    months_covered = -(-horizon_days // 30)  # arrondi superieur.
    payroll_projection = get_payroll_mass_projection(tenant, months=months_covered)

    outlook: dict[str, Any] = {
        "horizon_days": horizon_days,
        "generated_on": today,
        "overload_threshold_pct": overload_threshold_pct,
        "weeks": weeks,
        "payroll_projection": payroll_projection,
        "overloaded_week_starts": overloaded_week_starts,
    }

    if notify and overloaded_week_starts:
        _notify_overload(tenant, overloaded_week_starts, overload_threshold_pct)

    return outlook


def _notify_overload(
    tenant: Tenant, overloaded_week_starts: list[dt.date], overload_threshold_pct: Decimal
) -> None:
    """Alerte `direction` + `resp_production` (ajustement semi-automatique
    avec les decideurs, cf. plan) — reutilise `notify_role` deja construit,
    jamais un nouveau mecanisme de notification."""
    from apps.core.services.notifications import notify_role

    payload = {
        "overloaded_week_starts": [week.isoformat() for week in overloaded_week_starts],
        "overload_threshold_pct": str(overload_threshold_pct),
        "message": _(
            "Charge de production planifiée supérieure au seuil sur %(count)s semaine(s) "
            "de l'horizon 90 jours."
        )
        % {"count": len(overloaded_week_starts)},
    }
    for role_code in ("direction", "resp_production"):
        notify_role(str(tenant.id), role_code, "strategy.capacity_overload", payload)
