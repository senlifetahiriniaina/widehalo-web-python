"""CRA (RG-MRP-9) et CRI (RG-MRP-10) : le CRA alimente simultanement le
cout facon reel (uniquement une fois valide, cf. `real_labor_cost()`),
le suivi de presence (futur module `presence`, hors perimetre ici) et la
productivite par atelier/operateur (rapports, cf. M7)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.sequences import next_reference
from apps.core.services.workflow import attempt_transition
from apps.mrp.models import MrpCra, MrpOrder, MrpWorkOrder, MrpWorkshop


def create_cra(
    *,
    tenant: Tenant,
    employee: User,
    workshop: MrpWorkshop,
    date: dt.date,
    hours: Decimal,
    work_order: MrpWorkOrder | None = None,
    order: MrpOrder | None = None,
    qty_done: Decimal = Decimal(0),
    qty_rejected: Decimal = Decimal(0),
    activity_type: str = "",
    comment: str = "",
) -> MrpCra:
    reference = next_reference(tenant, "MRP-CRA", timezone.now().year)
    return MrpCra.objects.create(
        tenant=tenant,
        reference=reference,
        employee=employee,
        workshop=workshop,
        work_order=work_order,
        order=order,
        date=date,
        hours=hours,
        qty_done=qty_done,
        qty_rejected=qty_rejected,
        activity_type=activity_type,
        comment=comment,
    )


def submit_cra(cra: MrpCra, user: User) -> MrpCra:
    attempt_transition(cra, "submit", user)
    cra.save(update_fields=["state"])
    return cra


def validate_cra(cra: MrpCra, user: User) -> MrpCra:
    attempt_transition(cra, "validate", user)
    cra.validated_by = user
    cra.validated_at = timezone.now()
    cra.save(update_fields=["state", "validated_by", "validated_at"])
    return cra


def reject_cra(cra: MrpCra, user: User) -> MrpCra:
    attempt_transition(cra, "reject", user)
    cra.save(update_fields=["state"])
    return cra


def real_labor_cost(order: MrpOrder) -> Decimal:
    """RG-MRP-6/test d'acceptance n°4 : seuls les CRA `validated` entrent
    dans le cout facon reel. Le taux horaire resolu est celui du poste de
    charge de l'ordre de travail rattache ; un CRA sans ordre de travail
    (rattache directement a l'ordre de fabrication) n'est pas valorise ici
    faute de poste de charge identifiable — limitation documentee, a lever
    si le besoin se presente."""
    total = Decimal(0)
    entries = order.cra_entries.filter(state=MrpCra.STATE_VALIDATED).select_related(
        "work_order__workcenter"
    )
    for cra in entries:
        if cra.work_order is None:
            continue
        total += cra.hours * cra.work_order.workcenter.cost_per_hour_mga
    return total
