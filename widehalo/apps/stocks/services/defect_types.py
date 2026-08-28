"""Types de defaut qualite (§5.8, ST1 du sous-sequencement `stocks` — cf.
plan) : creation de `StkDefectType`, referentiel consomme par
`StkQualityState` en ST3."""

from __future__ import annotations

from apps.core.models.tenant import Tenant
from apps.stocks.models import StkDefectType


def create_defect_type(
    *,
    tenant: Tenant,
    code: str,
    name: str,
    category: str,
    severity: str = StkDefectType.SEVERITY_MINEUR,
    default_action: str = "",
) -> StkDefectType:
    return StkDefectType.objects.create(
        tenant=tenant,
        code=code,
        name=name,
        category=category,
        severity=severity,
        default_action=default_action,
    )
