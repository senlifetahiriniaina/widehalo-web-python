"""AUTO3 (chantier Studio de workflow visuel) : enregistrement de l'action
`mrp` dans le registre partage `core.services.automation_registry`, appele
depuis `apps.py::ready()` — meme patron que
`apps.accounting.services.reports_registration`.

**Choix assume et disclosed** : `open_conformity_incident` (RG-PAT-8) cree
un `MrpCri` (`type="incident_qualite"`) rattache a un poste de travail et
un patron — meme profil de risque que `purchase.open_purchase_incident`
(document `draft` ouvert, aucune mutation d'un etat financier/de
production existant, entierement revu/traite par un humain ensuite). Deux
exemples suffisent pour ce premier chantier (cf. plan : "2-3 exemples
concrets, pas une couverture exhaustive")."""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.utils import timezone

from apps.core.services.automation_registry import register_action


def _adapter_open_conformity_incident(tenant_id: str, params: dict[str, Any]) -> str:
    del tenant_id  # `open_conformity_incident` derive le tenant du workcenter cible
    from apps.mrp.services.public import open_conformity_incident

    date_str = params.get("date")
    date = dt.date.fromisoformat(date_str) if date_str else timezone.now().date()
    incident_id = open_conformity_incident(
        workcenter_id=params["workcenter_id"],
        pattern_id=params["pattern_id"],
        date=date,
        description=params.get("description", ""),
        cause=params.get("cause", ""),
    )
    return str(incident_id)


def register_actions() -> None:
    register_action(
        code="mrp.open_conformity_incident",
        module="mrp",
        label="Ouvrir un incident de conformite",
        function=_adapter_open_conformity_incident,
        param_schema={
            "workcenter_id": "Identifiant du poste de travail",
            "pattern_id": "Identifiant du patron concerne",
            "description": "Description de l'incident",
            "cause": "Cause identifiee (optionnel)",
            "date": "Date au format ISO (optionnel, defaut = aujourd'hui)",
        },
    )
