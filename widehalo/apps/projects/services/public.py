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
existante, jamais un code special ecrit uniquement pour le studio.

**PJ13 (« Liaison KPI/Strategie »)** : `link_project_to_objective`/
`get_linked_objective_summary` ne sont pas non plus des gaps consommes par
un AUTRE module — ce sont les 2 fonctions qui cablent enfin
`PrjProject.linked_objective_id` (simple `UUIDField` neutre depuis PJ1,
jamais une FK, cf. docstring de `models.py`) au gap de LECTURE expose par
`strategy` (`apps.strategy.services.public.get_objective_summary`, ajoute
au meme chantier). Placees ici (plutot que dans un fichier `services/
strategy_link.py` dedie) par coherence avec `notify_project_owner`/
`flag_project_risk` ci-dessus : ce module reste assez petit pour que
`services/public.py` regroupe directement ses propres petits gaps/
integrations, sans multiplier les fichiers a une seule fonction."""

from __future__ import annotations

from typing import Any
from uuid import UUID

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


def link_project_to_objective(project: Any, objective_id: str | UUID | None) -> None:
    """Renseigne (ou efface, `objective_id=None`) `PrjProject.
    linked_objective_id` — AUCUNE validation contre `apps.strategy.
    StgObjective` a l'ecriture (regle de couplage n°1, cf. docstring de
    `models.py` : un simple `UUIDField` neutre, jamais une FK Django cross-
    app). Une reference perimee/etrangere n'est donc detectee qu'a la
    LECTURE, par `get_linked_objective_summary` ci-dessous, qui renvoie
    alors `None` plutot qu'une exception — meme discipline que le reste de
    ce fichier. `project` typé `Any` (pas `PrjProject`) pour eviter un
    import top-niveau de `apps.projects.models` dans ce contrat public,
    meme convention que `notify_project_owner`/`flag_project_risk`
    ci-dessus (import different — mais meme esprit de ne pas alourdir la
    surface d'import de ce fichier)."""
    project.linked_objective_id = objective_id
    project.save(update_fields=["linked_objective_id"])


def get_linked_objective_summary(project: Any) -> dict[str, Any] | None:
    """Widget KPI (PJ13, ecran detail projet) : resout `PrjProject.
    linked_objective_id` via `strategy.services.public.
    get_objective_summary` — SEUL point d'appel autorise vers `strategy`
    (regle de couplage n°1). Retourne `None` si `linked_objective_id` est
    vide OU si `strategy` ne retrouve aucun objectif ACTIF de ce tenant
    pour cet UUID (reference perimee/etrangere) — jamais une exception,
    meme discipline que le reste de ce fichier. L'EVM du projet
    (`services/evm.py::compute_evm_snapshot`) n'est PAS inclus ici : c'est
    une donnee PROPRE a `projects`, deja disponible sans passer par ce
    gap — l'appelant (vue/API) combine les deux, cf. `views.py::
    project_detail`."""
    from apps.strategy.services.public import get_objective_summary

    if project.linked_objective_id is None:
        return None
    return get_objective_summary(project.tenant, project.linked_objective_id)
