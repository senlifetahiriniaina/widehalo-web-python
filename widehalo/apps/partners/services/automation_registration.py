"""INT1 (chantier interactivite native inter-modules) : enregistrement de
l'action `partners.notify_role_of_duplicate` dans le registre partage
`core.services.automation_registry`, appele depuis `apps.py::ready()` —
meme patron que `apps.crm.services.automation_registration`/`apps.catalog.
services.automation_registration` (chantier Studio de workflow visuel).

**Choix assume et disclosed** : meme situation que `crm`/`catalog` (cf.
docstrings la-bas) — `partners` n'a aucune fonction `services.public`
dediee a la notification d'un role. Adaptateur MINIME direct vers `apps.
core.services.notifications.notify_role`, jamais une nouvelle logique
metier partners. Concu pour etre declenche par un flux abonne a
`partners.duplicate_alert_created` (cf. `apps.partners.services.onboarding.
create_partner`) pour notifier le role responsable de la revue des
doublons de fiches partenaires."""

from __future__ import annotations

from typing import Any

from apps.core.services.automation_registry import register_action


def _adapter_notify_role_of_duplicate(tenant_id: str, params: dict[str, Any]) -> None:
    from apps.core.services.notifications import notify_role

    notify_role(
        tenant_id,
        params["role_code"],
        params.get("notification_type", "partners.automation_alert"),
        {
            "partner_id": params.get("partner_id", ""),
            "duplicate_of_id": params.get("duplicate_of_id", ""),
            "body": params.get("note", ""),
        },
    )


def register_actions() -> None:
    register_action(
        code="partners.notify_role_of_duplicate",
        module="partners",
        label="Notifier un role d'un doublon de partenaire",
        function=_adapter_notify_role_of_duplicate,
        param_schema={
            "role_code": "Code du role a notifier",
            "partner_id": "Identifiant du partenaire nouvellement cree (optionnel)",
            "duplicate_of_id": "Identifiant du partenaire duplique (optionnel)",
            "note": "Contenu du message a transmettre",
            "notification_type": "Type de notification (optionnel)",
        },
    )
