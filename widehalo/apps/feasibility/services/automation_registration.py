"""INT1 (chantier interactivite native inter-modules) : enregistrement de
l'action `feasibility.notify_study_completed` dans le registre partage
`core.services.automation_registry`, appele depuis `apps.py::ready()` —
meme patron que `apps.crm.services.automation_registration`/`apps.catalog.
services.automation_registration` (chantier Studio de workflow visuel).

**Choix assume et disclosed** : meme situation que `crm`/`catalog`/
`partners`/`patronage` (cf. docstrings la-bas) — `feasibility` n'a aucune
fonction `services.public` dediee a la notification d'un role. Adaptateur
MINIME direct vers `apps.core.services.notifications.notify_role`, jamais
une nouvelle logique metier feasibility. Notifie PAR DEFAUT `direction` ET
`resp_commercial` (les deux roles cites au cadrage de ce chantier pour la
completion d'une etude) — `role_codes` reste parametrable pour un flux qui
voudrait cibler un role different, mais le repli par defaut couvre
directement le besoin exprime sans configuration supplementaire. Concu
pour etre declenche par un flux abonne a `feasibility.study_completed`
(cf. `apps.feasibility.services.simulation.complete_study`)."""

from __future__ import annotations

from typing import Any

from apps.core.services.automation_registry import register_action

DEFAULT_NOTIFIED_ROLES = ("direction", "resp_commercial")


def _adapter_notify_study_completed(tenant_id: str, params: dict[str, Any]) -> None:
    from apps.core.services.notifications import notify_role

    role_codes = params.get("role_codes") or list(DEFAULT_NOTIFIED_ROLES)
    payload = {
        "study_id": params.get("study_id", ""),
        "body": params.get("note", ""),
    }
    notification_type = params.get("notification_type", "feasibility.study_completed")
    for role_code in role_codes:
        notify_role(tenant_id, role_code, notification_type, payload)


def register_actions() -> None:
    register_action(
        code="feasibility.notify_study_completed",
        module="feasibility",
        label="Notifier direction/resp_commercial d'une etude terminee",
        function=_adapter_notify_study_completed,
        param_schema={
            "study_id": "Identifiant de l'etude de faisabilite concernee (optionnel)",
            "note": "Contenu du message a transmettre",
            "role_codes": (
                "Liste des codes de role a notifier (optionnel, defaut : "
                "direction + resp_commercial)"
            ),
            "notification_type": "Type de notification (optionnel)",
        },
    )
