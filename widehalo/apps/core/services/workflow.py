"""Point d'entree unique pour declencher une transition de machine a etat
en respectant la garde par permission — ne JAMAIS appeler directement la
methode decoree par `@transition` depuis un module metier, toujours passer
par `attempt_transition()` pour que le controle RBAC soit effectif.

`user` accepte `User | None` (HD2, chantier `helpdesk`, cf.
`apps.helpdesk.services.escalation.run_escalation_checks`) : `None` ne
represente PAS un contournement du controle RBAC — `has_transition_perm`
consulte `Transition.has_perm`, qui retourne `True` sans jamais toucher a
`user` quand la transition ne declare AUCUN `permission=` (cf.
`django_fsm.Transition.has_perm`) ; `None` n'est donc exploitable en
pratique que pour un declenchement AUTOMATIQUE d'une transition SANS garde
de permission declaree (le seul cas ou aucun controle n'est de toute facon
contourne). Une transition qui declare `permission=` refusera `None`
normalement des que `user.has_perm(...)` serait appele sur lui."""

from __future__ import annotations

from typing import Any

from django.contrib.contenttypes.models import ContentType
from django_fsm import TransitionNotAllowed, has_transition_perm

from apps.core.models.user import User
from apps.core.models.workflow import StateTransitionLog


class TransitionPermissionError(Exception):
    pass


def attempt_transition(
    instance: Any,
    method_name: str,
    user: User | None,
    *args: Any,
    comment: str = "",
    **kwargs: Any,
) -> Any:
    bound_method = getattr(instance, method_name)

    # `has_transition_perm` est type par `django-fsm-2` pour un utilisateur
    # reel (jamais `None`) — cf. docstring de tete de module pour la preuve
    # que `None` reste sans danger tant qu'aucune transition ne declare
    # `permission=`.
    if not has_transition_perm(bound_method, user):  # type: ignore[arg-type]
        _log_refusal(instance, method_name, user, comment)
        raise TransitionPermissionError(
            f"{user} n'a pas la permission d'exécuter la transition '{method_name}'."
        )

    instance._transition_actor = user  # noqa: SLF001 — lu par workflows.py
    instance._transition_comment = comment  # noqa: SLF001
    try:
        return bound_method(*args, **kwargs)
    except TransitionNotAllowed:
        _log_refusal(instance, method_name, user, comment)
        raise


def _log_refusal(instance: Any, method_name: str, user: User | None, comment: str) -> None:
    bound_method = getattr(instance, method_name)
    field_name = bound_method._django_fsm.field.name  # noqa: SLF001
    current_state = getattr(instance, field_name, "?")
    StateTransitionLog.objects.create(
        content_type=ContentType.objects.get_for_model(instance.__class__),
        object_id=str(instance.pk),
        field_name=field_name,
        from_state=str(current_state),
        to_state=str(current_state),
        performed_by=user,
        was_refused=True,
        comment=comment,
    )
