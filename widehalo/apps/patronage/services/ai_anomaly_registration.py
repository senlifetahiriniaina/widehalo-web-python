"""INT2 : auto-enregistrement d'une verification d'anomalie DETERMINISTE du
module `patronage` dans `core.services.anomaly_registry`, appele depuis
`apps.py::ready()` — meme patron exact que `apps.helpdesk.services.
ai_anomaly_registration.register_ai_anomaly_checks()` deja etabli dans ce
chantier.

**Adaptateur mince, pas une nouvelle regle metier** : `_check_pending_eco_
validations` ne fait QUE surfacer les `ApprovalRequest` DEJA crees par
`apps.patronage.services.eco.enforce_eco_validation` (PAT-ECO1) pour la
regle `RULE_NAME` — un changement de version de patron dont l'analyse
d'impact reste `STATUS_PENDING` au-dela d'un delai raisonnable est un
blocage de production potentiel, directement actionnable (relancer
l'approbateur `resp_production`). Aucun nouveau calcul d'impact/de regle
d'approbation n'est introduit ici."""

from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from apps.core.models.workflow import ApprovalRequest
from apps.core.services.anomaly_registry import (
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    AnomalyCandidate,
    register_anomaly_check,
)

_PENDING_THRESHOLD_DAYS = 7


def _check_pending_eco_validations(tenant_id: str) -> list[AnomalyCandidate]:
    from apps.patronage.models import PatPattern
    from apps.patronage.services.eco import RULE_NAME

    now = timezone.now()
    content_type = ContentType.objects.get_for_model(PatPattern)
    requests = ApprovalRequest.objects.filter(
        rule__tenant_id=tenant_id,
        rule__name=RULE_NAME,
        content_type=content_type,
        status=ApprovalRequest.STATUS_PENDING,
    )

    candidates: list[AnomalyCandidate] = []
    for request in requests:
        age_days = (now - request.created_at).days
        if age_days < _PENDING_THRESHOLD_DAYS:
            continue

        severity = SEVERITY_HIGH if age_days >= _PENDING_THRESHOLD_DAYS * 2 else SEVERITY_MEDIUM
        candidates.append(
            AnomalyCandidate(
                content_type_label="patronage.patpattern",
                object_id=request.object_id,
                severity=severity,
                description=(
                    f"Changement de version de patron en attente de validation ECO "
                    f"depuis {age_days} jour(s)."
                ),
            )
        )

    return candidates


def register_ai_anomaly_checks() -> None:
    register_anomaly_check(
        "patronage.pending_eco_validation",
        module="patronage",
        label="Validation ECO de patron en attente prolongee",
        function=_check_pending_eco_validations,
    )
