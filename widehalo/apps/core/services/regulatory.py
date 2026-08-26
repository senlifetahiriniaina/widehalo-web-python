from __future__ import annotations

import datetime
from typing import Any

from django.db.models import Q

from apps.core.models.regulatory import RegulatoryParameter
from apps.core.models.tenant import Tenant


def get_parameter(code: str, at_date: datetime.date, tenant: Tenant | None = None) -> Any:
    """Resout la valeur d'un parametre reglementaire a une date donnee —
    une valeur specifique au tenant prevaut sur la valeur globale si les
    deux existent pour la meme plage."""
    base_filter = (
        Q(code=code)
        & Q(valid_from__lte=at_date)
        & (Q(valid_to__isnull=True) | Q(valid_to__gte=at_date))
    )

    if tenant is not None:
        tenant_specific = RegulatoryParameter.objects.filter(base_filter, tenant=tenant).first()
        if tenant_specific:
            return tenant_specific.value

    global_value = RegulatoryParameter.objects.filter(base_filter, tenant__isnull=True).first()
    if global_value is None:
        raise RegulatoryParameter.DoesNotExist(
            f"Aucun paramètre réglementaire '{code}' valide au {at_date}."
        )
    return global_value.value
