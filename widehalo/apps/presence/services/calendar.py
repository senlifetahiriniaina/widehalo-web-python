"""Jours feries (CDC `prs_public_holiday`) — reutilisation de
`core.RegulatoryParameter` (Lot 1 etape 10) plutot qu'un modele dedie, cf.
docstring de `apps/presence/models.py`. Chaque jour ferie est une ligne
`code="presence.public_holiday"`, `valid_from=valid_to=<date>`,
`value={"name": ..., "is_worked": bool, "pay_rate_pct": "150.00"}`."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from apps.core.models.regulatory import RegulatoryParameter

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant

PUBLIC_HOLIDAY_CODE = "presence.public_holiday"


def set_public_holiday(
    tenant: Tenant,
    *,
    date: dt.date,
    name: str,
    is_worked: bool = False,
    pay_rate_pct: Decimal = Decimal("100"),
) -> RegulatoryParameter:
    parameter, _created = RegulatoryParameter.objects.update_or_create(
        tenant=tenant,
        code=PUBLIC_HOLIDAY_CODE,
        valid_from=date,
        defaults={
            "valid_to": date,
            "value": {
                "name": name,
                "is_worked": is_worked,
                "pay_rate_pct": str(pay_rate_pct),
            },
        },
    )
    return parameter


def get_public_holiday(tenant: Tenant, date: dt.date) -> dict[str, Any] | None:
    parameter = RegulatoryParameter.objects.filter(
        tenant=tenant, code=PUBLIC_HOLIDAY_CODE, valid_from=date, valid_to=date
    ).first()
    return parameter.value if parameter else None


def list_public_holidays(
    tenant: Tenant, *, date_from: dt.date, date_to: dt.date
) -> list[tuple[dt.date, dict[str, Any]]]:
    parameters = RegulatoryParameter.objects.filter(
        tenant=tenant,
        code=PUBLIC_HOLIDAY_CODE,
        valid_from__gte=date_from,
        valid_from__lte=date_to,
    ).order_by("valid_from")
    return [(parameter.valid_from, parameter.value) for parameter in parameters]


def is_public_holiday(tenant: Tenant, date: dt.date) -> bool:
    return get_public_holiday(tenant, date) is not None
