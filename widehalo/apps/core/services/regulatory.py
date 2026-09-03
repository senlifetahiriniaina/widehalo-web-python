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
    param = _resolve_parameter(code, at_date, tenant)
    return param.value


def get_parameter_with_version(
    code: str, at_date: datetime.date, tenant: Tenant | None = None
) -> tuple[Any, int]:
    """Meme resolution que `get_parameter`, mais renvoie aussi `version` —
    ajoute pour le module `simulation` (SIM-3 : "un scenario enregistre
    conserve... la version des parametres reglementaires appliques"), qui a
    besoin de savoir QUELLE version d'un parametre (ex. `tva.taux_normal`)
    a servi a construire un socle de simulation donne, pas seulement sa
    valeur courante."""
    param = _resolve_parameter(code, at_date, tenant)
    return param.value, param.version


def _resolve_parameter(
    code: str, at_date: datetime.date, tenant: Tenant | None = None
) -> RegulatoryParameter:
    base_filter = (
        Q(code=code)
        & Q(valid_from__lte=at_date)
        & (Q(valid_to__isnull=True) | Q(valid_to__gte=at_date))
    )

    if tenant is not None:
        tenant_specific = RegulatoryParameter.objects.filter(base_filter, tenant=tenant).first()
        if tenant_specific:
            return tenant_specific

    global_param = RegulatoryParameter.objects.filter(base_filter, tenant__isnull=True).first()
    if global_param is None:
        raise RegulatoryParameter.DoesNotExist(
            f"Aucun paramètre réglementaire '{code}' valide au {at_date}."
        )
    return global_param
