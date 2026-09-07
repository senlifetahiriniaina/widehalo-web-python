"""Decorateur `@idempotent` pour les endpoints django-ninja qui mutent des
donnees sensibles (comptable, stock...). L'en-tete `Idempotency-Key` est
obligatoire sur ces endpoints ; rejouer la meme cle avec le meme corps
renvoie la reponse originale sans dupliquer l'effet.

**Le TTL est desormais tenu** (S4). Il ne l'etait pas : `expires_at` etait
ecrit et jamais filtre, si bien qu'une clef rejouait sa reponse
indefiniment et que le `unique_together` en interdisait la reutilisation
pour toujours. Trois pieces le rendent effectif — le filtre a la lecture,
le retrait de la ligne perimee avant reecriture, et la purge periodique
(`core.purge_idempotency_keys`). Les trois sont necessaires : sans la
purge, la table croit sans fin ; sans le retrait, l'appel legitime remonte
une `IntegrityError` ; sans le filtre, rien ne change.

**Ce que ce module ne fait PAS, et qui est signale ailleurs.**
`IdempotencyKey` n'herite pas de `BaseModel` : la table n'est donc pas sous
Row-Level Security. Ce n'est pas une fuite atteignable — la seule lecture
du depot filtre explicitement sur `tenant_id` ET `user_id`, et le
`unique_together` porte sur le meme triplet — mais c'est un filet de
securite absent. Ce cas n'est pas isole : DIX modeles portent un
discriminant de tenant sans passer par `BaseModel`, donc hors du perimetre
de `apply_rls`, qui selectionne sur `issubclass(model, BaseModel)`. La
garde `tests/architecture/test_rls_coverage.py` rend cet angle mort
visible et le fige."""

from __future__ import annotations

import functools
import hashlib
import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from django.http import JsonResponse
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.errors import ProblemDetailResponse
from apps.core.models.idempotency import IdempotencyKey

DEFAULT_TTL = timedelta(hours=24)


def _hash_body(request: Any) -> str:
    return hashlib.sha256(request.body or b"").hexdigest()


def idempotent(func: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(func)
    def wrapper(request: Any, *args: Any, **kwargs: Any) -> Any:
        key = request.headers.get("Idempotency-Key")
        if not key:
            return ProblemDetailResponse(
                status=400,
                title=_("En-tête Idempotency-Key manquant"),
                detail=_("Cet endpoint exige un en-tête Idempotency-Key sur les requêtes POST."),
                instance=request.path,
            )

        request_hash = _hash_body(request)
        user = getattr(request, "auth", None)
        tenant_id = getattr(request, "tenant_id", None)
        user_id = getattr(user, "id", None)

        # Le TTL est OPPOSABLE, et il ne l'etait pas. `expires_at` etait
        # ecrit a la creation (24 h) et filtre par aucune lecture : une clef
        # rejouait sa reponse indefiniment, et — plus genant — le
        # `unique_together` en interdisait la reutilisation POUR TOUJOURS.
        # Un client qui recycle ses clefs sur une periode glissante voyait
        # donc ses requetes legitimes renvoyer une reponse vieille de
        # plusieurs mois. Le champ etait purement descriptif.
        now = timezone.now()
        existing = IdempotencyKey.objects.filter(
            tenant_id=tenant_id, user_id=user_id, key=key, expires_at__gt=now
        ).first()
        if existing:
            if existing.request_hash != request_hash:
                return ProblemDetailResponse(
                    status=409,
                    title=_("Conflit de clé d'idempotence"),
                    detail=_(
                        "Cette clé Idempotency-Key a déjà été utilisée avec un corps différent."
                    ),
                    instance=request.path,
                )
            return JsonResponse(
                json.loads(existing.response_body),
                status=existing.response_status,
                safe=False,
            )

        result = func(request, *args, **kwargs)

        if isinstance(result, JsonResponse):
            status_code = result.status_code
            body_text = result.content.decode("utf-8")
            response_to_return: Any = result
        else:
            # Contrat du decorateur : la vue renvoie un dict JSON-serialisable
            # (pas une HttpResponse) — le decorateur se charge de la reponse.
            status_code = 200
            body_text = json.dumps(result)
            response_to_return = JsonResponse(result, safe=False)

        # La ligne PERIMEE du meme triplet est retiree avant d'ecrire la
        # neuve. Sans cela, faire respecter le TTL a la lecture ne suffirait
        # pas : le `unique_together` rejetterait la creation et l'appel
        # legitime remonterait une `IntegrityError`. Le TTL doit etre tenu
        # aux DEUX bouts, sans quoi l'appliquer a un seul le rend pire
        # qu'absent.
        IdempotencyKey.objects.filter(
            tenant_id=tenant_id, user_id=user_id, key=key, expires_at__lte=now
        ).delete()
        IdempotencyKey.objects.create(
            tenant_id=tenant_id,
            user_id=user_id,
            key=key,
            request_hash=request_hash,
            response_status=status_code,
            response_body=body_text,
            expires_at=now + DEFAULT_TTL,
        )
        return response_to_return

    return wrapper
