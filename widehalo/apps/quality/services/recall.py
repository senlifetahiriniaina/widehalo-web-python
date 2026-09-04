"""Bloc D, D4 (QUA-4 à QUA-7) : dossier de rappel — appelle
`stocks.services.public.lot_genealogy_tree` (pas de recalcul dupliqué),
snapshotte le résultat, et met en quarantaine le lot d'origine ET tous
ses descendants via `stocks.services.public.set_quality_state` (déjà
cross-app, déjà utilisé par `services/measurements.py::record_measurement`
pour ce rôle exact — jamais un second mécanisme de blocage).

Distinct de `apps.stocks.StkRecall`, qui continue d'exister tel quel —
décision D5 actée : coexistence délibérée, pas une migration/retrait
différé (cf. docstring de `QltRecallDossier`)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.sequences import next_reference
from apps.quality.models import QltRecallDossier
from apps.quality.services.generic_ref import resolve_generic_reference
from apps.stocks.services.public import QUALITY_STATE_QUARANTINE
from apps.stocks.services.public import lot_genealogy_tree as _lot_genealogy_tree
from apps.stocks.services.public import set_quality_state as _set_stock_quality_state


def _serialize_value(value: Any) -> Any:
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, dict):
        return {key: _serialize_value(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    return value


def _flatten_descendants(nodes: list[dict[str, Any]]) -> list[dict[str, str]]:
    """(lot_variant_id, lot_name) dédupliqué, parcours récursif de
    `descendants[]` (cf. forme exacte retournée par
    `stocks.services.genealogy.genealogy_tree`)."""
    seen: set[tuple[str, str]] = set()
    flat: list[dict[str, str]] = []

    def _walk(items: list[dict[str, Any]]) -> None:
        for node in items:
            key = (str(node["variant_id"]), node["lot_name"])
            if key not in seen:
                seen.add(key)
                flat.append({"lot_variant_id": key[0], "lot_name": key[1]})
            _walk(node["children"])

    _walk(nodes)
    return flat


@transaction.atomic
def declare_recall(
    *,
    tenant: Tenant,
    lot_variant_id: Any,
    lot_name: str,
    reason: str,
    initiated_by: User,
    content_object: models.Model | None = None,
) -> QltRecallDossier:
    """`@transaction.atomic` : la mise en quarantaine de TOUS les lots
    impactés et la création du dossier doivent réussir ou échouer
    ensemble — jamais un dossier créé sans que chaque lot concerné soit
    effectivement bloqué (ou l'inverse)."""
    if not reason:
        raise ValidationError(_("Un motif est obligatoire pour déclarer un rappel."))

    tree = _lot_genealogy_tree(tenant=tenant, variant_id=lot_variant_id, name=lot_name)
    if tree is None:
        raise ValidationError(_("Lot introuvable — impossible de déclarer un rappel."))

    impacted_lots = [
        {"lot_variant_id": str(lot_variant_id), "lot_name": lot_name},
        *_flatten_descendants(tree["descendants"]),
    ]

    for entry in impacted_lots:
        _set_stock_quality_state(
            tenant,
            variant_id=entry["lot_variant_id"],
            lot_name=entry["lot_name"],
            state=QUALITY_STATE_QUARANTINE,
            description=reason,
            decided_by=initiated_by,
        )

    reference = next_reference(tenant, "QLT-RECALL", timezone.now().year)
    return QltRecallDossier.objects.create(
        tenant=tenant,
        reference=reference,
        lot_variant_id=lot_variant_id,
        lot_name=lot_name,
        reason=reason,
        genealogy_snapshot=_serialize_value(tree),
        impacted_lots=impacted_lots,
        initiated_by=initiated_by,
        **resolve_generic_reference(content_object),
    )


def close_recall(
    dossier: QltRecallDossier, *, closed_by: User, closing_reason: str
) -> QltRecallDossier:
    """Clôture administrative — NE libère PAS la quarantaine des lots
    impactés (décision qualité distincte et délibérée, même discipline
    que `stocks.services.recall.close_recall`)."""
    if not closing_reason:
        raise ValidationError(_("Un motif est obligatoire pour clôturer un dossier de rappel."))
    if dossier.state == QltRecallDossier.STATE_CLOSED:
        raise ValidationError(_("Ce dossier de rappel est déjà clôturé."))
    dossier.state = QltRecallDossier.STATE_CLOSED
    dossier.closed_by = closed_by
    dossier.closed_at = timezone.now()
    dossier.closing_reason = closing_reason
    dossier.save(update_fields=["state", "closed_by", "closed_at", "closing_reason"])
    return dossier
