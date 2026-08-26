"""Pagination par curseur generique, reutilisable par tout futur module
metier pour ses endpoints de liste. Curseur opaque (base64) encodant la
derniere valeur de tri + le dernier id — pas d'offset SQL couteux sur de
grandes tables."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from django.db.models import Model, QuerySet

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

M = TypeVar("M", bound=Model)


@dataclass
class Page(Generic[M]):  # noqa: UP046 (PEP 695 requiert Python 3.12 pour l'analyse statique)
    items: list[M]
    next_cursor: str | None


def encode_cursor(sort_value: Any, pk: Any) -> str:
    payload = json.dumps([str(sort_value), str(pk)]).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii")


def decode_cursor(cursor: str) -> tuple[str, str]:
    payload = base64.urlsafe_b64decode(cursor.encode("ascii"))
    sort_value, pk = json.loads(payload)
    return sort_value, pk


def paginate(
    queryset: QuerySet[Any],
    *,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    order_by: str = "id",
) -> Page[Any]:
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    ordered = queryset.order_by(order_by)

    if cursor:
        sort_value, pk = decode_cursor(cursor)
        ordered = ordered.filter(**{f"{order_by}__gt": sort_value}) | ordered.filter(
            **{order_by: sort_value, "pk__gt": pk}
        )
        ordered = ordered.order_by(order_by)

    items = list(ordered[: limit + 1])
    has_more = len(items) > limit
    items = items[:limit]

    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor(getattr(last, order_by), last.pk)

    return Page(items=items, next_cursor=next_cursor)
