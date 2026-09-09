"""T9 — la seule lecture de `logistics` qui ait lieu SANS societe active, et
elle ne rend qu'une chose : quelle societe activer.

Meme forme, meme motif et meme portee que `flows/services/inbound_routing`
au lot T5 : un transporteur qui appelle
`/api/v1/logistics/webhooks/carrier/{provider_id}` n'a ni session, ni
jeton, ni en-tete de societe. Le prestataire EST donc l'unique moyen de
savoir quelle societe activer — et `log_service_provider` est en `FORCE ROW
LEVEL SECURITY`.

**La fenetre ne rend qu'un identifiant de societe**, jamais l'objet, et
surtout jamais le secret : celui-ci se lit ensuite normalement, sous la
societe du prestataire, par le manager en refus par defaut. Le routage
n'authentifie rien ; c'est la signature qui juge, et elle est verifiee
apres.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError

from apps.core.db.webhook_lookup import webhook_lookup_window
from apps.core.identifiers import parse_uuid
from apps.logistics.models import LogServiceProvider

if TYPE_CHECKING:
    from uuid import UUID


def resolve_tenant_for_carrier_call(provider_id: Any) -> UUID | None:
    """La societe a activer pour traiter un appel de transporteur.

    Rend `None` si le prestataire n'existe pas ou si l'identifiant est
    illisible — les deux se traduisent par le meme 404 : distinguer
    « inconnu » de « mal forme » apprendrait quelque chose a qui essaie."""
    try:
        identifiant = parse_uuid(str(provider_id), champ="prestataire")
    except ValidationError:
        return None

    with webhook_lookup_window():
        # `.order_by()` par prudence heritee de T5 : un tri par cle
        # etrangere ferait joindre une table restee en `FORCE` et la
        # requete rendrait zero ligne alors que la ligne existe.
        # `LogServiceProvider.Meta` ne declare aujourd'hui aucun ordre —
        # le vider coute donc rien et protege du jour ou quelqu'un en
        # ajoutera un.
        return (
            LogServiceProvider.all_objects.filter(id=identifiant)
            .order_by()
            .values_list("tenant_id", flat=True)
            .first()
        )


__all__ = ["resolve_tenant_for_carrier_call"]
