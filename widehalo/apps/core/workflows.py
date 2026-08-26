"""Moteur de workflow generique : connecte une fois pour toutes au signal
`django_fsm.post_transition`, journalise automatiquement toute transition
de n'importe quel modele metier futur utilisant un FSMField — aucun code
supplementaire requis dans les modules metier pour beneficier du journal.

La garde par permission N'EST PAS automatique (django_fsm ne l'impose pas) :
tout appelant DOIT passer par `attempt_transition()` (services/workflow.py)
qui verifie `has_transition_perm()` avant d'invoquer la methode de
transition, sans quoi la permission declaree sur `@transition(permission=...)`
ne serait jamais effectivement controlee.
"""

from __future__ import annotations

from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db.models import Model
from django_fsm.signals import post_transition


def _log_transition_receiver(
    sender: type[Model],
    instance: Any,
    name: str,
    field: Any,
    source: str,
    target: str,
    **kwargs: Any,
) -> None:
    from apps.core.events import publish_event
    from apps.core.models.workflow import StateTransitionLog

    content_type = ContentType.objects.get_for_model(sender)
    StateTransitionLog.objects.create(
        content_type=content_type,
        object_id=str(instance.pk),
        field_name=field.name,
        from_state=source,
        to_state=target,
        performed_by=getattr(instance, "_transition_actor", None),
        comment=getattr(instance, "_transition_comment", ""),
    )
    publish_event(
        "workflow.transitioned",
        {
            "model": f"{sender._meta.app_label}.{sender.__name__}",
            "object_id": str(instance.pk),
            "field": field.name,
            "source": source,
            "target": target,
        },
    )


def connect_workflow_signals() -> None:
    post_transition.connect(_log_transition_receiver, weak=False)
