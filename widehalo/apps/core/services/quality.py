"""Service qualite generique (QLT1-2).

Point d'entree normatif pour creer une `QltInspection` — calcule `passed`
(`False` ssi AU MOINS un critere de `results` est `RESULT_NONCONFORME`,
jamais saisi directement, cf. docstring de `apps.core.models.quality`) et
notifie les roles pertinents quand l'inspection echoue, ce qui permet une
reaction rapide (reprise/tri/blocage) SANS qu'un module metier n'ait besoin
d'importer `QltInspection` (regle de couplage n°5).

**Roles notifies en cas d'echec (choix assume)** : `resp_production` (pilote
operationnel de la qualite en atelier, role cible de ce lot, cf. cadrage
QLT1-2) et `direction` (visibilite transverse sur un incident qualite,
meme niveau d'alerte que `RiskItem.score` haut qui remonte a
admin/direction). Reutilise `apps.core.services.notifications.notify_role`
(mecanisme deja existant, jamais duplique) — PAS un nouveau modele
d'incident : contrairement a `apps.mrp`/`apps.purchase` qui ouvrent un
`MrpCri`/`PurCri` dedie pour un incident qualite/reception, ce lot reste
volontairement plus simple (disclosed, budget de modeles impose par le
cadrage : exactement 2 nouveaux modeles) — une notification suffit pour
declencher le suivi humain ; l'ouverture d'un ticket de non-conformite
structure (workflow `ApprovalRule`/`ApprovalRequest`, ou futur modele
dedie) reste un travail futur si le besoin reel se confirme."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db.models import QuerySet

from apps.core.models.quality import RESULT_NONCONFORME, QltChecklistTemplate, QltInspection
from apps.core.models.tenant import Tenant
from apps.core.models.user import User

# Roles notifies quand une inspection echoue (cf. docstring de module).
FAILURE_NOTIFICATION_ROLES = ("resp_production", "direction")


def _compute_passed(results: list[dict[str, Any]]) -> bool:
    """`passed=True` ssi aucun critere n'a le statut `non_conforme` — un
    `observation` seul ne fait pas echouer l'inspection (cf. docstring de
    `apps.core.models.quality`)."""
    return not any(entry.get("status") == RESULT_NONCONFORME for entry in results)


def create_checklist_template(
    *,
    tenant: Tenant,
    name: str,
    created_by: User | None = None,
    sector_code: str = "",
    items: list[dict[str, Any]] | None = None,
) -> QltChecklistTemplate:
    return QltChecklistTemplate.objects.create(
        tenant=tenant,
        created_by=created_by,
        name=name,
        sector_code=sector_code,
        items=items or [],
    )


def create_inspection(
    *,
    tenant: Tenant,
    template: QltChecklistTemplate,
    inspector: User,
    results: list[dict[str, Any]],
    inspected_at: datetime,
    created_by: User | None = None,
    content_object: Any = None,
) -> QltInspection:
    """Cree une `QltInspection`, `content_object=None` pour une inspection
    "a blanc" (pas rattachee a une entite precise) — meme idiome que
    `apps.core.services.risk.create_risk_item`. Publie une notification vers
    `FAILURE_NOTIFICATION_ROLES` si l'inspection echoue (`passed=False`)."""
    passed = _compute_passed(results)
    inspection = QltInspection.objects.create(
        tenant=tenant,
        created_by=created_by or inspector,
        content_type=(
            None
            if content_object is None
            else ContentType.objects.get_for_model(content_object.__class__)
        ),
        object_id="" if content_object is None else str(content_object.pk),
        template=template,
        results=results,
        passed=passed,
        inspector=inspector,
        inspected_at=inspected_at,
    )
    if not passed:
        from apps.core.services.notifications import notify_role

        for role_code in FAILURE_NOTIFICATION_ROLES:
            notify_role(
                str(tenant.id),
                role_code,
                "quality.inspection_failed",
                {
                    "inspection_id": str(inspection.id),
                    "template_id": str(template.id),
                    "template_name": template.name,
                    "inspector_id": str(inspector.id),
                },
            )
    return inspection


def list_inspections_for(content_object: Any) -> QuerySet[QltInspection]:
    """Inspections rattachees a une entite donnee (ordre anti-chronologique)
    — retourne toutes les inspections du tenant si `content_object` est
    `None` (usage generique, meme idiome que le reste du module)."""
    if content_object is None:
        return QltInspection.objects.all().order_by("-inspected_at")
    content_type = ContentType.objects.get_for_model(content_object.__class__)
    return QltInspection.objects.filter(
        content_type=content_type, object_id=str(content_object.pk)
    ).order_by("-inspected_at")
