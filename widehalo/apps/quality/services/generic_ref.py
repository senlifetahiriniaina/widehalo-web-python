"""Resolution du couple `content_type`/`object_id` pour un rattachement
generique optionnel — meme idiome exact que `apps.core.services.risk.
create_risk_item`/`apps.core.services.quality.create_inspection` : NE
JAMAIS passer `content_object=` directement a `Model.objects.create()`
quand il peut valoir `None` (`GenericForeignKey.__set__` assigne alors
`object_id=None`, pas `""`, ce qui viole la contrainte NOT NULL du champ —
piege reel rencontre a l'implementation de D1, corrige ici une bonne fois
plutot que reproduit a chaque site d'appel)."""

from __future__ import annotations

from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db import models


def resolve_generic_reference(content_object: models.Model | None) -> dict[str, Any]:
    """Retourne `{"content_type": ..., "object_id": ...}`, prêt à être
    déballé (`**`) dans un `Model.objects.create(...)`."""
    if content_object is None:
        return {"content_type": None, "object_id": ""}
    return {
        "content_type": ContentType.objects.get_for_model(content_object.__class__),
        "object_id": str(content_object.pk),
    }
