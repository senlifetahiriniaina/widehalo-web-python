"""Contrat public de l'app `mrp` — seule surface que les autres apps
metier (`patronage`, futur `sales`) ont le droit d'importer (cf.
tests/architecture/test_module_boundaries.py)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.mrp.models import MrpBom, MrpBomLine, MrpWorkcenter
from apps.mrp.services.interventions import create_cri


def set_bom_line_qty_by_size(
    *, bom_id: Any, component_variant_id: Any, qty_by_size: dict[str, Decimal]
) -> bool:
    """RG-PAT-5 : point d'integration central pour
    `patronage.services.push_to_bom()` — alimente `qty_by_size` (RG-MRP-2)
    de la ligne de nomenclature dont le composant correspond a la matiere
    du patron. Retourne False si aucune ligne ne correspond (jamais une
    exception silencieuse deguisee en succes)."""
    bom = MrpBom.objects.get(id=bom_id)
    if bom.state == MrpBom.STATE_ACTIVE:
        raise ValidationError(
            _("Une nomenclature active est immuable — creer une nouvelle version.")
        )

    line = MrpBomLine.objects.filter(
        bom_id=bom_id, component_variant_id=component_variant_id
    ).first()
    if line is None:
        return False

    line.qty_by_size = {size: str(qty) for size, qty in qty_by_size.items()}
    line.save(update_fields=["qty_by_size"])
    return True


def open_conformity_incident(
    *,
    workcenter_id: Any,
    pattern_id: Any,
    date: dt.date,
    description: str,
    cause: str = "",
) -> UUID:
    """RG-PAT-8 : un incident de conformite constate en production ouvre un
    CRI rattache au patron d'origine, pour identifier les patrons generant
    le plus de reprises."""
    workcenter = MrpWorkcenter.objects.get(id=workcenter_id)
    cri = create_cri(
        tenant=workcenter.tenant,
        type="incident_qualite",
        workcenter=workcenter,
        date=date,
        description=description,
        cause=cause,
        pattern_id=pattern_id,
    )
    cri_id: UUID = cri.id
    return cri_id
