"""Limite de debit generique (1000 req/h/utilisateur par defaut), via un
compteur Redis (cache Django). Decorateur reutilisable par tout endpoint
django-ninja."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from django.core.cache import cache
from django.utils.translation import gettext as _

from apps.core.errors import ProblemDetailResponse

DEFAULT_LIMIT = 1000
WINDOW_SECONDS = 3600


def throttle(
    limit: int = DEFAULT_LIMIT, window: int = WINDOW_SECONDS
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(request: Any, *args: Any, **kwargs: Any) -> Any:
            user = getattr(request, "auth", None)
            identifier = getattr(user, "id", None) or request.META.get("REMOTE_ADDR", "anon")
            cache_key = f"ratelimit:{identifier}"

            count = cache.get(cache_key, 0)
            if count >= limit:
                return ProblemDetailResponse(
                    status=429,
                    title=_("Trop de requêtes"),
                    detail=_("Limite de débit dépassée, réessayez plus tard."),
                    instance=request.path,
                )
            if count == 0:
                cache.set(cache_key, 1, timeout=window)
            else:
                cache.incr(cache_key)
            return func(request, *args, **kwargs)

        return wrapper

    return decorator
