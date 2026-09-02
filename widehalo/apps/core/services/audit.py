from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.contrib.contenttypes.models import ContentType

from apps.core.context import get_current_tenant_id
from apps.core.models.audit import AuditLog
from apps.core.models.user import User


def log_action(
    action: str,
    *,
    actor: User | None = None,
    obj: Any = None,
    changes: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Point d'entree generique du journal d'audit — utilisable depuis
    n'importe quel module (connexion, export, changement de permission,
    acces a une donnee personnelle...), pas seulement pour les creations/
    modifications/suppressions deja tracees automatiquement (cf.
    apps/core/apps.py::ready(), signaux post_save/post_delete)."""
    content_type = None
    object_id = ""
    if obj is not None:
        content_type = ContentType.objects.get_for_model(obj.__class__)
        object_id = str(obj.pk)

    return AuditLog.objects.create(
        tenant_id=get_current_tenant_id(),
        actor=actor,
        action=action,
        content_type=content_type,
        object_id=object_id,
        changes=changes or {},
        metadata=metadata or {},
    )


def log_pii_access(actor: User, obj: Any, fields: list[str]) -> AuditLog:
    return log_action(AuditLog.ACTION_PII_ACCESS, actor=actor, obj=obj, metadata={"fields": fields})


def compute_field_diff(old_values: dict[str, Any], new_values: dict[str, Any]) -> dict[str, Any]:
    """Calcule un diff champ-par-champ entre deux dicts de valeurs deja
    extraites (`Model.all_objects.filter(pk=...).values(...)` pour
    `old_values`, attributs courants de l'instance pour `new_values`) —
    chantier "fiche partenaire a onglets par role" (PT11), consomme par
    `Partner.save()`.

    Un champ scalaire different produit `{"before": x, "after": y}` ;
    un champ dont la valeur est une liste/tuple (ex. `roles`) produit
    `{"added": [...], "removed": [...]}` via difference d'ensembles.
    Un champ identique (ou absent de l'un des deux dicts) n'apparait pas
    dans le resultat — jamais de bruit pour les champs inchanges.

    Chaque valeur est passee par `_json_safe()` avant d'entrer dans le
    resultat : `changes` est un `JSONField` sans `encoder=DjangoJSONEncoder`
    (Lot 1) — un `Decimal` brut (ex. `credit_limit_mga`) ferait echouer
    l'ecriture en base avec `TypeError: Object of type Decimal is not JSON
    serializable`, decouvert par un test reel plutot que devine."""
    diff: dict[str, Any] = {}
    for key, new_value in new_values.items():
        if key not in old_values:
            continue
        old_value = old_values[key]
        if isinstance(old_value, list | tuple) or isinstance(new_value, list | tuple):
            old_set = set(old_value or [])
            new_set = set(new_value or [])
            added = sorted(_json_safe(v) for v in (new_set - old_set))
            removed = sorted(_json_safe(v) for v in (old_set - new_set))
            if added or removed:
                diff[key] = {"added": added, "removed": removed}
            continue
        if old_value != new_value:
            diff[key] = {"before": _json_safe(old_value), "after": _json_safe(new_value)}
    return diff


def _json_safe(value: Any) -> Any:
    """Rend `value` serialisable en JSON pour un `JSONField` sans
    `encoder=DjangoJSONEncoder` — seul `Decimal` (montants) pose probleme
    parmi les types deja rencontres par `compute_field_diff`; converti en
    chaine pour preserver la precision exacte (jamais `float`, meme
    discipline monetaire que le reste du projet)."""
    if isinstance(value, Decimal):
        return str(value)
    return value
