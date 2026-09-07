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

from apps.core.context import get_current_tenant_id


def _tenant_id_of(instance: Any) -> str | None:
    """La societe a qui appartient la transition.

    Deux sources, dans cet ordre et pas l'inverse :

    1. **L'instance elle-meme.** Tout `BaseModel` porte `tenant_id`, et
       c'est la seule source qui ne peut pas mentir : la ligne appartient a
       cette societe-la, quel que soit le contexte depuis lequel on la fait
       transiter.
    2. **Le contexte ambiant**, pour les rares modeles a FSMField qui ne
       sont pas des `BaseModel` (`Tenant` lui-meme, par exemple). Sous RLS
       une ecriture n'aboutit de toute facon que dans le contexte de sa
       societe, donc les deux coincident quand les deux existent.

    Renvoie `None` quand ni l'une ni l'autre n'est disponible — une
    transition faite par une commande d'administration hors contexte, par
    exemple. L'evenement est alors publie sans societe, exactement comme
    avant : il est journalise, mais ne declenche aucun flux
    d'automatisation."""
    tenant_id = getattr(instance, "tenant_id", None)
    if tenant_id:
        return str(tenant_id)
    return get_current_tenant_id()


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
    # Le `tenant_id` n'est PAS decoratif ici : `automation/services/
    # dispatch.py` sort immediatement quand il manque, si bien qu'aucun
    # `AutoFlow` branche sur une transition ne pouvait se declencher —
    # alors que `projects/services/automation_registration.py` en
    # documente un ("quand une tache est terminee"). Vingt-cinq des
    # vingt-six publieurs de production attribuaient deja une societe ;
    # celui-ci, le plus general de tous, etait le seul a ne pas le faire.
    publish_event(
        "workflow.transitioned",
        {
            "model": f"{sender._meta.app_label}.{sender.__name__}",
            "object_id": str(instance.pk),
            "field": field.name,
            "source": source,
            "target": target,
        },
        tenant_id=_tenant_id_of(instance),
    )


def connect_workflow_signals() -> None:
    post_transition.connect(_log_transition_receiver, weak=False)
