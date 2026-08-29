"""AUTO3 (chantier Studio de workflow visuel) — action `core` enregistree
dans `core.services.automation_registry`, appelee depuis
`apps.core.apps.py::ready()` (meme patron que chaque module metier qui
enregistre ses propres actions/rapports)."""

from __future__ import annotations

from typing import Any

from apps.core.services.automation_registry import register_action


def _adapter_notify_role(tenant_id: str, params: dict[str, Any]) -> list[str]:
    """Notifie tous les utilisateurs du role `role_code` pour le tenant du
    flux — action deja construite et sans effet de bord dangereux (une
    simple `Notification` par destinataire, RG deja verifiee par
    `apps.core.tests.test_notifications`), choix naturel de premiere
    action disponible pour tout flux (le seul builtin, jamais retire du
    registre)."""
    from apps.core.services.notifications import notify_role

    notifications = notify_role(
        tenant_id,
        params["role_code"],
        params.get("notification_type", "automation.flow_notification"),
        params.get("payload", {}),
    )
    return [str(n.id) for n in notifications]


def register_actions() -> None:
    register_action(
        code="core.notify_role",
        module="core",
        label="Notifier un role",
        function=_adapter_notify_role,
        param_schema={
            "role_code": "Code du role a notifier (ex. 'direction')",
            "notification_type": "Type de notification (optionnel)",
            "payload": "Donnees libres jointes a la notification (optionnel)",
        },
    )
