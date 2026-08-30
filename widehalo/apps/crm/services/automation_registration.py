"""INT1 (chantier interactivite native inter-modules) : enregistrement de
l'action `crm.notify_role_of_opportunity` dans le registre partage
`core.services.automation_registry`, appele depuis `apps.py::ready()` —
meme patron que `apps.mrp.services.automation_registration`/`apps.purchase.
services.automation_registration`/`apps.projects.services.
automation_registration` (chantier Studio de workflow visuel).

**Choix assume et disclosed** : `crm` n'a, a ce jour, aucune fonction
`services.public` dediee a la notification d'un role au sujet d'une
opportunite (contrairement a `purchase.open_purchase_incident`/
`projects.notify_project_owner` deja construites pour un autre besoin) —
conformement a la discipline explicite de ce chantier ("si aucune fonction
adaptee n'existe pour un module donne, cree une fonction MINIME... qui
appelle `core.notify_role`/`dispatch_notification`"), cette action est un
adaptateur MINIME direct vers `apps.core.services.notifications.
notify_role`, jamais une nouvelle logique metier crm. Declenchable
typiquement par un flux abonne a `crm.opportunity_stage_changed`
(cf. `apps.crm.services.pipeline.move_lead_to_stage`) pour notifier le
role `resp_commercial` d'une opportunite perdue/gagnee/etape franchie."""

from __future__ import annotations

from typing import Any

from apps.core.services.automation_registry import register_action


def _adapter_notify_role_of_opportunity(tenant_id: str, params: dict[str, Any]) -> None:
    from apps.core.services.notifications import notify_role

    notify_role(
        tenant_id,
        params["role_code"],
        params.get("notification_type", "crm.automation_alert"),
        {
            "lead_id": params.get("lead_id", ""),
            "body": params.get("note", ""),
        },
    )


def register_actions() -> None:
    register_action(
        code="crm.notify_role_of_opportunity",
        module="crm",
        label="Notifier un role au sujet d'une opportunite",
        function=_adapter_notify_role_of_opportunity,
        param_schema={
            "role_code": "Code du role a notifier (ex. resp_commercial)",
            "lead_id": "Identifiant de l'opportunite concernee (optionnel)",
            "note": "Contenu du message a transmettre",
            "notification_type": "Type de notification (optionnel)",
        },
    )
