"""Seul point d'appel a Django-Q2 dans tout le projet — permet de basculer
vers un autre backend (Celery) sans modifier le reste du code. Verifie par
`tests/architecture/test_no_direct_task_queue_usage.py`."""

from __future__ import annotations

from typing import Any


def enqueue(func: Any, *args: Any, task_name: str | None = None, **kwargs: Any) -> str:
    from django_q.tasks import async_task

    task_id: str = async_task(func, *args, task_name=task_name, **kwargs)
    return task_id
