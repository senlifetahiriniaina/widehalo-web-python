"""INT1 (chantier interactivite native inter-modules) : enregistrement de
l'action `catalog.notify_role_of_catalog_issue` dans le registre partage
`core.services.automation_registry`, appele depuis `apps.py::ready()` —
meme patron que `apps.crm.services.automation_registration`/`apps.mrp.
services.automation_registration` (chantier Studio de workflow visuel).

**Choix assume et disclosed** : meme situation que `crm` (cf. docstring de
ce module la-bas) — `catalog` n'a aucune fonction `services.public` dediee
a la notification d'un role au sujet d'une anomalie de referentiel (gamme,
variante, reference produit). Adaptateur MINIME direct vers `apps.core.
services.notifications.notify_role`, jamais une nouvelle logique metier
catalog. Declenchable typiquement par un flux abonne a
`catalog.variants_generated` (cf. `apps.catalog.services.variants.
generate_variants`) pour notifier un role d'une generation de variantes a
verifier."""

from __future__ import annotations

from typing import Any

from apps.core.services.automation_registry import register_action


def _adapter_notify_role_of_catalog_issue(tenant_id: str, params: dict[str, Any]) -> None:
    from apps.core.services.notifications import notify_role

    notify_role(
        tenant_id,
        params["role_code"],
        params.get("notification_type", "catalog.automation_alert"),
        {
            "template_id": params.get("template_id", ""),
            "body": params.get("note", ""),
        },
    )


def register_actions() -> None:
    register_action(
        code="catalog.notify_role_of_catalog_issue",
        module="catalog",
        label="Notifier un role d'une anomalie de referentiel produit",
        function=_adapter_notify_role_of_catalog_issue,
        param_schema={
            "role_code": "Code du role a notifier",
            "template_id": "Identifiant de la gamme concernee (optionnel)",
            "note": "Contenu du message a transmettre",
            "notification_type": "Type de notification (optionnel)",
        },
    )
