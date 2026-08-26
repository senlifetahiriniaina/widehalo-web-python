from __future__ import annotations

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tasks import enqueue

pytestmark = pytest.mark.django_db


def _create_tenant_task(code: str) -> None:
    Tenant.objects.create(code=code, name="Créé par une tâche async")


def test_enqueue_runs_the_task_in_sync_mode() -> None:
    """Q_CLUSTER['sync']=True en tests : enqueue() execute la tache
    immediatement, sans worker separe. Verifie un effet durable (ecriture
    en base) plutot qu'une mutation d'objet Python local — django-q serialise
    toujours ses arguments via une file, meme en mode synchrone, donc muter
    un objet Python passe par valeur ne serait pas visible depuis le test."""
    enqueue(_create_tenant_task, "TASK-CREATED")
    assert Tenant.objects.filter(code="TASK-CREATED").exists()
