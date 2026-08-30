"""INT2 : auto-enregistrement d'une verification d'anomalie DETERMINISTE du
module `crm` dans `core.services.anomaly_registry`, appele depuis
`apps.py::ready()` — meme patron exact que `apps.helpdesk.services.
ai_anomaly_registration.register_ai_anomaly_checks()` deja etabli dans ce
chantier.

**Adaptateur mince, pas une nouvelle regle metier** : `_check_stagnant_
opportunities` ne fait QUE surfacer des champs DEJA portes par `CrmLead`/
`CrmActivity` (`won_at`/`lost_at`/`CrmActivity.created_at`) — aucun nouveau
calcul introduit ici.

**Deviation disclosed par rapport a une lecture litterale du plan**
(« CrmLead dans le meme stage depuis plus de N jours ») : `CrmLead` ne
porte AUCUN horodatage d'entree de stage (`stage_changed_at` n'existe pas,
seul `updated_at` existe et est touche par TOUTE modification du lead, pas
seulement un changement d'etape — l'utiliser reviendrait a une fausse
precision). **Metrique retenue a la place, honnetement calculable depuis
les donnees existantes** : une opportunite encore ouverte
(`won_at`/`lost_at` tous deux `NULL`) sans AUCUNE `CrmActivity` enregistree
depuis `_STAGNANT_WINDOW_DAYS` jours (ou, si aucune activite n'a jamais ete
enregistree, depuis sa creation) — un signal de stagnation authentique et
directement actionnable (« relancer ce lead »), sans supposer un
horodatage de changement d'etape qui n'est pas trace."""

from __future__ import annotations

import datetime as dt

from django.db.models import Max
from django.utils import timezone

from apps.core.services.anomaly_registry import (
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    AnomalyCandidate,
    register_anomaly_check,
)

_STAGNANT_WINDOW_DAYS = 21


def _check_stagnant_opportunities(tenant_id: str) -> list[AnomalyCandidate]:
    from apps.crm.models import CrmLead

    now = timezone.now()
    cutoff = now - dt.timedelta(days=_STAGNANT_WINDOW_DAYS)

    leads = (
        CrmLead.objects.filter(tenant_id=tenant_id, is_active=True)
        .filter(won_at__isnull=True, lost_at__isnull=True)
        .select_related("stage")
        .annotate(last_activity_at=Max("activities__created_at"))
    )

    candidates: list[AnomalyCandidate] = []
    for lead in leads:
        reference_date = lead.last_activity_at or lead.created_at
        if reference_date > cutoff:
            continue

        days_stagnant = (now - reference_date).days
        severity = SEVERITY_HIGH if days_stagnant >= _STAGNANT_WINDOW_DAYS * 2 else SEVERITY_MEDIUM
        candidates.append(
            AnomalyCandidate(
                content_type_label="crm.crmlead",
                object_id=str(lead.id),
                severity=severity,
                description=(
                    f"Opportunite « {lead.name} » (etape « {lead.stage.name} ») sans "
                    f"activite enregistree depuis {days_stagnant} jour(s)."
                ),
            )
        )

    return candidates


def register_ai_anomaly_checks() -> None:
    register_anomaly_check(
        "crm.stagnant_opportunity",
        module="crm",
        label="Opportunite stagnante (aucune activite recente)",
        function=_check_stagnant_opportunities,
    )
