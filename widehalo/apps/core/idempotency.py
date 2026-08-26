"""Decorateur `@idempotent` pour les endpoints django-ninja qui mutent des
donnees sensibles (comptable, stock...). L'en-tete `Idempotency-Key` est
obligatoire sur ces endpoints ; rejouer la meme cle avec le meme corps
renvoie la reponse originale sans dupliquer l'effet."""

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

        existing = IdempotencyKey.objects.filter(
            tenant_id=tenant_id, user_id=user_id, key=key
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

        IdempotencyKey.objects.create(
            tenant_id=tenant_id,
            user_id=user_id,
            key=key,
            request_hash=request_hash,
            response_status=status_code,
            response_body=body_text,
            expires_at=timezone.now() + DEFAULT_TTL,
        )
        return response_to_return

    return wrapper
