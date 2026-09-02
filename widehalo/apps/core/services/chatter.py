from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.db.models import QuerySet

from apps.core.models.base import BaseModel
from apps.core.models.chatter import ChatterMessage
from apps.core.models.user import User


def thread_for(instance: BaseModel) -> QuerySet[ChatterMessage]:
    """Fil de discussion (messages + notes internes) attache a `instance`,
    par ordre chronologique — meme resolution de content_type/object_id
    que `apps.core.services.public` fait deja pour l'audit trail (jamais
    de requete brute dupliquee par appelant)."""
    content_type = ContentType.objects.get_for_model(instance)
    return ChatterMessage.objects.filter(content_type=content_type, object_id=str(instance.pk))


def post_message(
    instance: BaseModel, *, author: User, body: str, is_note: bool = False
) -> ChatterMessage:
    """Poste un message ou une note interne sur le fil de `instance`. Le
    parametre est type `BaseModel` (pas `Model`) precisement pour que
    `instance.tenant_id` reste type-safe : le chatter n'a de sens que sur
    un enregistrement tenant-scope, jamais un modele hors socle."""
    content_type = ContentType.objects.get_for_model(instance)
    return ChatterMessage.objects.create(
        tenant_id=instance.tenant_id,
        content_type=content_type,
        object_id=str(instance.pk),
        author=author,
        body=body,
        is_note=is_note,
    )
