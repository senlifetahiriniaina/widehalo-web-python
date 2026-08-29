"""Contrat public de l'app `projects` — seule surface que les autres apps
metier ont le droit d'importer (cf. tests/architecture/
test_module_boundaries.py).

**PJ11** : `notify_project_owner`/`flag_project_risk` ne sont pas des gaps
consommes par un AUTRE module metier — ce sont les deux fonctions
enregistrees comme actions du Studio de workflow visuel
(`apps.core.services.automation_registry`, cf. `services/
automation_registration.py::register_actions`), meme discipline que
`mrp.open_conformity_incident`/`purchase.open_purchase_incident` : une
action d'automatisation est toujours une fonction `services.public`
existante, jamais un code special ecrit uniquement pour le studio."""

from __future__ import annotations

from apps.core.models.tenant import Tenant
from apps.core.models.user import User


def notify_project_owner(project_id: str, notification_type: str, message: str) -> None:
    """Notifie le proprietaire (`PrjProject.owner`) d'un projet — reutilise
    `core.services.notifications.dispatch_notification` tel quel, jamais
    une duplication du mecanisme de notification. `owner` est nullable sur
    `PrjProject` (cf. `models.py`) : un projet sans proprietaire ne peut
    pas etre notifie, l'action ne fait alors rien plutot que de lever une
    exception pour un cas de configuration incomplete, meme discipline que
    les gaps `accounting.create_*_invoice_from_source` qui renvoient
    `None` sur configuration incomplete."""
    from apps.core.services.notifications import dispatch_notification
    from apps.projects.models import PrjProject

    project = PrjProject.objects.select_related("owner").get(id=project_id)
    if project.owner is None:
        return
    dispatch_notification(
        project.owner,
        notification_type,
        {"project_id": str(project.id), "message": message},
        tenant_id=str(project.tenant_id),
    )


def flag_project_risk(
    project_id: str, *, likelihood: int, impact: int, mitigation_plan: str = ""
) -> str | None:
    """Signale un risque rattache a un projet — reutilise `core.services.
    risk.create_risk_item(content_object=project, category=CATEGORY_
    PROJECT)` tel quel (PJ9), jamais un nouveau registre de risques.
    `RiskItem.owner` est obligatoire (jamais nullable) — si le projet n'a
    pas de `owner` (nullable, cf. `models.py`), aucun risque ne peut etre
    cree ; retourne `None` plutot qu'une exception, meme discipline que
    `notify_project_owner` ci-dessus."""
    from apps.core.models.risk import CATEGORY_PROJECT
    from apps.core.services.risk import create_risk_item
    from apps.projects.models import PrjProject

    project = PrjProject.objects.select_related("owner", "tenant").get(id=project_id)
    if project.owner is None:
        return None
    tenant: Tenant = project.tenant
    owner: User = project.owner
    risk_item = create_risk_item(
        tenant=tenant,
        category=CATEGORY_PROJECT,
        likelihood=likelihood,
        impact=impact,
        owner=owner,
        mitigation_plan=mitigation_plan,
        content_object=project,
    )
    return str(risk_item.id)
