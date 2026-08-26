"""RG-PAT-8 : lien avec CRA/CRI. Les etapes de montage definies dans le
patron alimentent la gamme operatoire MRP (donc les ordres de travail,
donc les CRA) — cette partie reste un rattachement manuel de la gamme au
patron via `PatPattern.product_template_id`/`MrpRouting.product_template_id`
communs, aucune nouvelle entite structuree n'etant listee par le CDC pour
des « etapes de montage » distinctes des pieces du patron. Un incident de
conformite constate en production ouvre en revanche un CRI rattache au
patron, via `mrp.services.public.open_conformity_incident()` — jamais
d'import direct de `apps.mrp.models` depuis `patronage`."""

from __future__ import annotations

import datetime as dt
from uuid import UUID

from apps.mrp.services.public import open_conformity_incident
from apps.patronage.models import PatPattern


def report_conformity_incident(
    pattern: PatPattern,
    *,
    workcenter_id: UUID,
    description: str,
    cause: str = "",
    date: dt.date | None = None,
) -> UUID:
    """Retourne l'id du CRI cree, permettant a l'appelant de le consulter
    via l'API/rapports `mrp` (identification des patrons generant le plus
    de reprises, cf. RG-PAT-8)."""
    return open_conformity_incident(
        workcenter_id=workcenter_id,
        pattern_id=pattern.id,
        date=date or dt.date.today(),
        description=description,
        cause=cause,
    )
