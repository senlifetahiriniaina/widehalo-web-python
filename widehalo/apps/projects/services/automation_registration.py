"""PJ11 (chantier « module `projects` ») : enregistrement des actions
`projects` dans le registre partage `core.services.automation_registry`,
appele depuis `apps.py::ready()` — meme patron que `apps.mrp.services.
automation_registration`/`apps.purchase.services.automation_registration`
(chantier Studio de workflow visuel).

**Aucun nouveau `event_type` necessaire (choix assume et disclosed)** :
`PrjTask.state` utilise deja `WorkflowMixin`/`attempt_transition()`
(cf. `apps/projects/services/tasks.py`), donc CHAQUE transition (y compris
`finish_task` -> `state="done"`) publie deja automatiquement l'evenement
generique `workflow.transitioned` (`apps/core/workflows.py`, connecte une
fois pour toutes au signal `django_fsm.post_transition`) avec
`payload={"model": "projects.PrjTask", "target": "done", ...}`. Un flux du
Studio de workflow visuel peut donc DEJA se declencher sur "tache projet
terminee" en filtrant `trigger_event_type="workflow.transitioned"` avec un
`trigger_filter` sur `payload.model`/`payload.target` — ajouter un
`event_type` dedie (ex. `projects.task_completed`) aurait ete une
duplication du mecanisme deja generique, pas un gap reel.

**Deux actions enregistrees (2-3 exemples suffisent pour ce premier
chantier, cf. precedent AUTO3)** : `projects.notify_project_owner` et
`projects.flag_project_risk` — toutes deux de simples adaptateurs vers des
fonctions `services.public` deja construites (`dispatch_notification`,
PJ9/`create_risk_item`), jamais un nouveau code metier ecrit uniquement
pour le studio."""

from __future__ import annotations

from typing import Any

from apps.core.services.automation_registry import register_action


def _adapter_notify_project_owner(tenant_id: str, params: dict[str, Any]) -> None:
    del tenant_id  # `notify_project_owner` derive le tenant du projet cible
    from apps.projects.services.public import notify_project_owner

    notify_project_owner(
        params["project_id"],
        params.get("notification_type", "projects.automation_alert"),
        params.get("notification_message", ""),
    )


def _adapter_flag_project_risk(tenant_id: str, params: dict[str, Any]) -> str | None:
    del tenant_id  # `flag_project_risk` derive le tenant du projet cible
    from apps.projects.services.public import flag_project_risk

    return flag_project_risk(
        params["project_id"],
        likelihood=int(params["likelihood"]),
        impact=int(params["impact"]),
        mitigation_plan=params.get("mitigation_plan", ""),
    )


def register_actions() -> None:
    register_action(
        code="projects.notify_project_owner",
        module="projects",
        label="Notifier le proprietaire du projet",
        function=_adapter_notify_project_owner,
        param_schema={
            "project_id": "Identifiant du projet",
            "notification_type": "Type de notification (optionnel)",
            "notification_message": "Contenu du message a transmettre",
        },
    )
    register_action(
        code="projects.flag_project_risk",
        module="projects",
        label="Signaler un risque projet",
        function=_adapter_flag_project_risk,
        param_schema={
            "project_id": "Identifiant du projet",
            "likelihood": "Probabilite (1-5)",
            "impact": "Impact (1-5)",
            "mitigation_plan": "Plan d'attenuation (optionnel)",
        },
    )
