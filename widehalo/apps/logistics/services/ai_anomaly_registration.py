"""INT2 : auto-enregistrement d'une verification d'anomalie DETERMINISTE du
module `logistics` dans `core.services.anomaly_registry`, appele depuis
`apps.py::ready()` — meme patron exact que `apps.helpdesk.services.
ai_anomaly_registration.register_ai_anomaly_checks()` deja etabli dans ce
chantier.

**Adaptateur mince, pas une nouvelle regle metier** : `_check_customs_
files_at_risk` ne fait QUE surfacer `LogCustomsFile.state`/`opened_at`,
DEJA portes par le modele (LOG5) — un dossier douanier reste ouvert
(`STATE_OPEN`, jamais dedouane) au-dela d'un delai raisonnable est un
risque d'immobilisation/de surcout (magasinage, penalites) directement
actionnable par le declarant en douane."""

from __future__ import annotations

import datetime as dt

from django.utils import timezone

from apps.core.services.anomaly_registry import (
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    AnomalyCandidate,
    register_anomaly_check,
)

# Seuil choisi et disclosed (aucune reference normative externe) : un
# dossier douanier ouvert depuis plus de 15 jours calendaires sans
# dedouanement est retenu comme "a risque" (immobilisation prolongee).
_OPEN_TOO_LONG_DAYS = 15


def _check_customs_files_at_risk(tenant_id: str) -> list[AnomalyCandidate]:
    from apps.logistics.models import LogCustomsFile

    today = timezone.now().date()
    cutoff = today - dt.timedelta(days=_OPEN_TOO_LONG_DAYS)

    files = LogCustomsFile.objects.filter(
        tenant_id=tenant_id,
        is_active=True,
        state=LogCustomsFile.STATE_OPEN,
        opened_at__lte=cutoff,
    ).select_related("shipment")

    candidates: list[AnomalyCandidate] = []
    for customs_file in files:
        age_days = (today - customs_file.opened_at).days
        severity = SEVERITY_HIGH if age_days >= _OPEN_TOO_LONG_DAYS * 2 else SEVERITY_MEDIUM
        candidates.append(
            AnomalyCandidate(
                content_type_label="logistics.logcustomsfile",
                object_id=str(customs_file.id),
                severity=severity,
                description=(
                    f"Dossier douanier {customs_file.reference} (expedition "
                    f"{customs_file.shipment.reference}) ouvert depuis {age_days} "
                    f"jour(s) sans dedouanement."
                ),
            )
        )

    return candidates


def register_ai_anomaly_checks() -> None:
    register_anomaly_check(
        "logistics.customs_file_at_risk",
        module="logistics",
        label="Dossier douanier ouvert depuis trop longtemps",
        function=_check_customs_files_at_risk,
    )
