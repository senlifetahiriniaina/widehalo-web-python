"""MRP-GMAO1 (enrichissement WideHalo) : GMAO minimale adossee a
`MrpWorkcenter`/`MrpCri` — plan de maintenance preventive et calcul
MTBF/MTTR a partir des interventions declarees."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from apps.mrp.models import MrpCri, MrpMaintenancePlan, MrpWorkcenter


def create_maintenance_plan(
    *,
    workcenter: MrpWorkcenter,
    name: str,
    trigger_type: str = MrpMaintenancePlan.TRIGGER_CALENDAR,
    interval_days: int | None = None,
    interval_hours: int | None = None,
) -> MrpMaintenancePlan:
    return MrpMaintenancePlan.objects.create(
        tenant=workcenter.tenant,
        workcenter=workcenter,
        name=name,
        trigger_type=trigger_type,
        interval_days=interval_days,
        interval_hours=interval_hours,
    )


def record_maintenance_done(plan: MrpMaintenancePlan, *, date: dt.date) -> MrpMaintenancePlan:
    plan.last_done_at = date
    if plan.trigger_type == MrpMaintenancePlan.TRIGGER_CALENDAR and plan.interval_days:
        plan.next_due_at = date + relativedelta(days=plan.interval_days)
    plan.save(update_fields=["last_done_at", "next_due_at"])
    return plan


def plans_due(
    *, on_date: dt.date, workcenter: MrpWorkcenter | None = None
) -> list[MrpMaintenancePlan]:
    queryset = MrpMaintenancePlan.objects.filter(is_active=True, next_due_at__lte=on_date)
    if workcenter is not None:
        queryset = queryset.filter(workcenter=workcenter)
    return list(queryset)


def compute_mtbf_mttr(workcenter: MrpWorkcenter) -> dict[str, Decimal]:
    """MTBF (temps moyen entre pannes) et MTTR (temps moyen de reparation),
    approches depuis les CRI de type panne du poste — pas de collecte IoT
    (differee V2 par le CDC lui-meme)."""
    breakdowns = list(
        MrpCri.objects.filter(workcenter=workcenter, type=MrpCri.TYPE_BREAKDOWN).order_by("date")
    )
    if not breakdowns:
        return {"mtbf_days": Decimal(0), "mttr_minutes": Decimal(0)}

    mttr_minutes = sum((Decimal(b.downtime_min) for b in breakdowns), Decimal(0)) / Decimal(
        len(breakdowns)
    )

    if len(breakdowns) < 2:
        return {"mtbf_days": Decimal(0), "mttr_minutes": mttr_minutes}

    gaps = [(breakdowns[i].date - breakdowns[i - 1].date).days for i in range(1, len(breakdowns))]
    mtbf_days = Decimal(sum(gaps)) / Decimal(len(gaps))
    return {"mtbf_days": mtbf_days, "mttr_minutes": mttr_minutes}
