"""INT2 : auto-enregistrement d'une verification d'anomalie DETERMINISTE du
module `partners` dans `core.services.anomaly_registry`, appele depuis
`apps.py::ready()` — meme patron exact que `apps.helpdesk.services.
ai_anomaly_registration.register_ai_anomaly_checks()` deja etabli dans ce
chantier.

**Adaptateur mince, pas une nouvelle regle metier** : `_check_unresolved_
duplicate_alerts` ne fait QUE lister les `DuplicateAlert` non resolues
(`resolved_at IS NULL`) DEJA levees par le mecanisme existant de detection
de doublon (meme NIF, cf. docstring `models.py::DuplicateAlert`) — AUCUN
nouveau calcul de similarite n'est introduit ici, conformement a la
consigne explicite de ce chantier."""

from __future__ import annotations

from apps.core.services.anomaly_registry import (
    SEVERITY_MEDIUM,
    AnomalyCandidate,
    register_anomaly_check,
)


def _check_unresolved_duplicate_alerts(tenant_id: str) -> list[AnomalyCandidate]:
    from apps.partners.models import DuplicateAlert

    alerts = DuplicateAlert.objects.filter(
        tenant_id=tenant_id, is_active=True, resolved_at__isnull=True
    ).select_related("partner", "duplicate_of")

    return [
        AnomalyCandidate(
            content_type_label="partners.duplicatealert",
            object_id=str(alert.id),
            severity=SEVERITY_MEDIUM,
            description=(
                f"Doublon potentiel non resolu entre « {alert.partner.name} » et "
                f"« {alert.duplicate_of.name} » (champ « {alert.matched_field} »)."
            ),
        )
        for alert in alerts
    ]


def register_ai_anomaly_checks() -> None:
    register_anomaly_check(
        "partners.unresolved_duplicate_alert",
        module="partners",
        label="Alerte de doublon partenaire non resolue",
        function=_check_unresolved_duplicate_alerts,
    )
