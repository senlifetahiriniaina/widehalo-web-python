"""AUTO3 (chantier Studio de workflow visuel) — creation/edition d'un
`AutoFlow`/`AutoStep`, VALIDEE contre les mecanismes reels plutot que de
laisser passer une chaine libre non verifiee (cf. plan) : le declencheur
doit correspondre a un `event_type` reellement publie
(`core.events.PUBLISHED_EVENT_TYPES`), une etape `action` doit reference
un code reellement enregistre dans `core.services.automation_registry`."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.automation.models import STEP_TYPE_ACTION, STEP_TYPE_CONDITION, AutoFlow, AutoStep
from apps.core.events import PUBLISHED_EVENT_TYPES
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.automation_registry import get_registered_action
from apps.core.services.sequences import next_reference


def create_flow(
    tenant: Tenant,
    *,
    name: str,
    trigger_event_type: str,
    description: str = "",
    trigger_filter: dict[str, Any] | None = None,
    created_by: User | None = None,
) -> AutoFlow:
    """Cree un flux INACTIF (`is_active=False` par defaut, cf. `AutoFlow`)
    — jamais actif des la creation, une activation est une action
    explicite separee (`set_flow_active`)."""
    if trigger_event_type not in PUBLISHED_EVENT_TYPES:
        raise ValidationError(
            _(
                "'%(event_type)s' ne correspond a aucun evenement reellement "
                "publie (cf. core.events.PUBLISHED_EVENT_TYPES)."
            )
            % {"event_type": trigger_event_type}
        )
    reference = next_reference(tenant, "AUTO", timezone.now().year)
    return AutoFlow.objects.create(
        tenant=tenant,
        reference=reference,
        name=name,
        description=description,
        trigger_event_type=trigger_event_type,
        trigger_filter=trigger_filter or {},
        created_by=created_by,
    )


def add_condition_step(
    flow: AutoFlow,
    *,
    expression: str,
    next_step: AutoStep | None = None,
    next_step_on_false: AutoStep | None = None,
) -> AutoStep:
    return AutoStep.objects.create(
        tenant=flow.tenant,
        flow=flow,
        step_type=STEP_TYPE_CONDITION,
        config={"expression": expression},
        next_step=next_step,
        next_step_on_false=next_step_on_false,
    )


def add_action_step(
    flow: AutoFlow,
    *,
    action_code: str,
    param_mapping: dict[str, Any] | None = None,
    next_step: AutoStep | None = None,
) -> AutoStep:
    if get_registered_action(action_code) is None:
        raise ValidationError(
            _("Action '%(code)s' non enregistree dans le catalogue d'automatisation.")
            % {"code": action_code}
        )
    return AutoStep.objects.create(
        tenant=flow.tenant,
        flow=flow,
        step_type=STEP_TYPE_ACTION,
        config={"action_code": action_code, "param_mapping": param_mapping or {}},
        next_step=next_step,
    )


def set_flow_active(flow: AutoFlow, *, is_active: bool) -> AutoFlow:
    flow.is_active = is_active
    flow.save(update_fields=["is_active"])
    return flow
