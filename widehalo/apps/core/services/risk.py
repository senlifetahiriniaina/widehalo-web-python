"""Service du registre de risques operationnels generique (RSK1-2).

Point d'entree normatif pour creer/mettre a jour/cloturer un `RiskItem` —
recalcule `score` (`likelihood * impact`, jamais saisi directement, cf.
docstring de `apps.core.models.risk`) et publie l'evenement `risk.flagged`
quand le score franchit `HIGH_SCORE_THRESHOLD`, ce qui permet au Studio de
workflow visuel deja construit (`apps.automation`, abonne via
`core.events.subscribe_all`) de reagir (notification, action) SANS aucune
modification de son propre code — seul `PUBLISHED_EVENT_TYPES` a du etre
etendu (cf. `apps.core.events`).

**Publication a la creation UNIQUEMENT (choix assume)** : `risk.flagged`
n'est publie qu'a la CREATION d'un `RiskItem` deja au-dessus du seuil, pas a
chaque mise a jour qui le ferait franchir le seuil a nouveau — evite un flot
d'evenements dupliques a chaque `update_risk_item` mineur (ex. modifier
`mitigation_plan` sans toucher `likelihood`/`impact`). `update_risk_item`
publie neanmoins l'evenement si la mise a jour fait FRANCHIR le seuil (le
risque n'etait pas signale comme eleve avant, il l'est apres) — jamais de
re-publication si le score reste au-dessus du seuil apres une mise a jour
qui ne fait que l'ajuster (ex. 20 -> 16, toujours "eleve", pas un nouveau
franchissement)."""

from __future__ import annotations

from datetime import date
from typing import Any

from django.contrib.contenttypes.models import ContentType

from apps.core.models.risk import HIGH_SCORE_THRESHOLD, STATUS_CLOSED, RiskItem
from apps.core.models.tenant import Tenant
from apps.core.models.user import User


def _maybe_publish_flagged(risk_item: RiskItem) -> None:
    from apps.core.events import publish_event

    if risk_item.score < HIGH_SCORE_THRESHOLD:
        return
    publish_event(
        "risk.flagged",
        {
            "risk_item_id": str(risk_item.id),
            "category": risk_item.category,
            "likelihood": risk_item.likelihood,
            "impact": risk_item.impact,
            "score": risk_item.score,
            "owner_id": str(risk_item.owner_id),
        },
        tenant_id=str(risk_item.tenant_id),
    )


def create_risk_item(
    *,
    tenant: Tenant,
    category: str,
    likelihood: int,
    impact: int,
    owner: User,
    created_by: User | None = None,
    mitigation_plan: str = "",
    review_date: date | None = None,
    content_object: Any = None,
) -> RiskItem:
    """Cree un `RiskItem`, `content_object=None` pour un risque generique
    (pas rattache a une entite precise) — meme idiome que
    `apps.core.services.documents.store_document`."""
    risk_item = RiskItem.objects.create(
        tenant=tenant,
        created_by=created_by or owner,
        content_type=(
            None
            if content_object is None
            else ContentType.objects.get_for_model(content_object.__class__)
        ),
        object_id="" if content_object is None else str(content_object.pk),
        category=category,
        likelihood=likelihood,
        impact=impact,
        score=likelihood * impact,
        mitigation_plan=mitigation_plan,
        owner=owner,
        review_date=review_date,
    )
    _maybe_publish_flagged(risk_item)
    return risk_item


def update_risk_item(
    risk_item: RiskItem,
    *,
    updated_by: User | None = None,
    category: str | None = None,
    likelihood: int | None = None,
    impact: int | None = None,
    mitigation_plan: str | None = None,
    review_date: date | None = None,
) -> RiskItem:
    """Met a jour les champs fournis (les autres restent inchanges) et
    recalcule `score` si `likelihood`/`impact` a change. Publie
    `risk.flagged` UNIQUEMENT si cette mise a jour fait franchir le seuil
    (cf. docstring de module)."""
    was_high = risk_item.score >= HIGH_SCORE_THRESHOLD

    if category is not None:
        risk_item.category = category
    if likelihood is not None:
        risk_item.likelihood = likelihood
    if impact is not None:
        risk_item.impact = impact
    if mitigation_plan is not None:
        risk_item.mitigation_plan = mitigation_plan
    if review_date is not None:
        risk_item.review_date = review_date
    risk_item.score = risk_item.likelihood * risk_item.impact
    if updated_by is not None:
        risk_item.updated_by = updated_by

    risk_item.save(
        update_fields=[
            "category",
            "likelihood",
            "impact",
            "score",
            "mitigation_plan",
            "review_date",
            "updated_by",
            "updated_at",
        ]
    )

    if risk_item.score >= HIGH_SCORE_THRESHOLD and not was_high:
        _maybe_publish_flagged(risk_item)
    return risk_item


def close_risk_item(risk_item: RiskItem, *, closed_by: User | None = None) -> RiskItem:
    """Cloture un risque (statut `closed`) — jamais une suppression
    (soft-delete applicatif deja porte par `BaseModel.soft_delete`, distinct
    de ce statut metier : un risque cloture reste visible dans l'historique
    du registre, `is_active` n'est pas touche ici)."""
    risk_item.status = STATUS_CLOSED
    if closed_by is not None:
        risk_item.updated_by = closed_by
    risk_item.save(update_fields=["status", "updated_by", "updated_at"])
    return risk_item
