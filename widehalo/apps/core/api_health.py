from __future__ import annotations

from django.core.cache import cache
from django.db import connection
from ninja import Router

router = Router(tags=["health"])


@router.get("/live", auth=None)
def live(request):
    return {"status": "ok"}


@router.get("/ready", auth=None)
def ready(request):
    db_ok = _check_db()
    redis_ok = _check_redis()
    healthy = db_ok and redis_ok
    body = {"status": "ok" if healthy else "unavailable", "db": db_ok, "redis": redis_ok}
    if not healthy:
        from django.http import JsonResponse

        return JsonResponse(body, status=503)
    return body


def _check_db() -> bool:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except Exception:
        return False


def _check_redis() -> bool:
    try:
        cache.set("health_check_probe", "1", timeout=5)
        return cache.get("health_check_probe") == "1"
    except Exception:
        return False
