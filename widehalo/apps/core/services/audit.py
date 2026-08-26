from __future__ import annotations

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
