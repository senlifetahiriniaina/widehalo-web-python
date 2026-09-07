"""S4 — purge des clefs d'idempotence perimees.

**Pourquoi une purge est indispensable, et pas seulement propre.** Le TTL
de 24 h etait ecrit et jamais applique : la table grossissait d'une ligne
par appel idempotent, indefiniment, chacune portant le CORPS COMPLET de la
reponse (`response_body`, un `TextField`). Sur un endpoint de facturation
appele mille fois par jour, c'est mille reponses conservees pour toujours,
alors que leur duree utile est de vingt-quatre heures. Ce n'est pas une
question d'encombrement mais de gouvernance des donnees : le cahier fixe a
chaque enregistrement une retention propre, et une table qui n'oublie
jamais conserve des donnees personnelles hors de toute duree declaree.

**Un balayage global, et c'est le premier du depot.** Les deux purges
existantes (`sandbox`, `report_jobs`) bouclent tenant par tenant sous
`activate_tenant`, et leur motif est ecrit : la Row-Level Security empeche
de selectionner globalement, `all_objects` ne contournant que la RLS
applicative. Cette table n'etant PAS sous RLS (elle n'herite pas de
`BaseModel`, cf. `models/idempotency.py`), la contrainte ne s'applique pas
et un seul `DELETE` suffit. Rompre le patron des deux precedents est
deliberé, et c'est ecrit ici pour qu'on ne le prenne pas pour un oubli — le
jour ou cette table passerait sous RLS, cette fonction devrait reprendre la
boucle par tenant.
"""

from __future__ import annotations

from django.utils import timezone

from apps.core.models.idempotency import IdempotencyKey


def purge_expired_idempotency_keys() -> int:
    """Supprime les clefs dont la date d'expiration est passee.

    Idempotente au sens de L0-1 : deux passages successifs ne suppriment
    rien la seconde fois, et un passage sur une table propre n'ecrit rien.
    """
    expired = IdempotencyKey.objects.filter(expires_at__lte=timezone.now())
    count = expired.count()
    expired.delete()
    return count


__all__ = ["purge_expired_idempotency_keys"]
