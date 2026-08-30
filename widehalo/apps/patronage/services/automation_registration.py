"""INT1 (chantier interactivite native inter-modules) : enregistrement de
l'action `patronage.notify_role_of_pattern_version` dans le registre
partage `core.services.automation_registry`, appele depuis
`apps.py::ready()` — meme patron que `apps.crm.services.
automation_registration`/`apps.catalog.services.automation_registration`
(chantier Studio de workflow visuel).

**Choix assume et disclosed** : meme situation que `crm`/`catalog`/
`partners` (cf. docstrings la-bas) — `patronage` n'a aucune fonction
`services.public` dediee a la notification d'un role. Adaptateur MINIME
direct vers `apps.core.services.notifications.notify_role`, jamais une
nouvelle logique metier patronage. Concu pour etre declenche par un flux
abonne a `patronage.pattern_version_changed` (cf. `apps.patronage.services.
patterns.new_pattern_version`) pour notifier/faire consulter le role
`resp_production` d'un changement de version de patron."""

from __future__ import annotations

from typing import Any

from apps.core.services.automation_registry import register_action


def _adapter_notify_role_of_pattern_version(tenant_id: str, params: dict[str, Any]) -> None:
    from apps.core.services.notifications import notify_role

    notify_role(
        tenant_id,
        params["role_code"],
        params.get("notification_type", "patronage.automation_alert"),
        {
            "pattern_id": params.get("pattern_id", ""),
            "body": params.get("note", ""),
        },
    )


def register_actions() -> None:
    register_action(
        code="patronage.notify_role_of_pattern_version",
        module="patronage",
        label="Notifier un role d'un changement de version de patron",
        function=_adapter_notify_role_of_pattern_version,
        param_schema={
            "role_code": "Code du role a notifier (ex. resp_production)",
            "pattern_id": "Identifiant du patron concerne (optionnel)",
            "note": "Contenu du message a transmettre",
            "notification_type": "Type de notification (optionnel)",
        },
    )
