"""C-3 — les suites possibles d'une expedition et d'une tournee.

`LogShipment.state` est une machine `django_fsm` ; `LogTrip.status` est un
`CharField` dont les transitions vivent dans `services/trips.py`. Meme
partage que dans `sales`, et meme raison d'etre du registre."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from apps.core.models.user import User
from apps.core.services.next_steps import (
    NextStep,
    declared_next_steps,
    fsm_next_steps,
    register_next_steps,
)
from apps.logistics.models import LogTrip

_SHIPMENT_WRITE = "logistics.change_logshipment"
_TRIP_WRITE = "logistics.change_logtrip"

_SHIPMENT_LABELS = {
    "book": _("Réserver auprès du transporteur"),
    "pick_up": _("Enlèvement effectué"),
    "mark_in_transit": _("Marquer en transit"),
    "mark_arrived_at_port": _("Arrivée au port"),
    "start_customs_clearance": _("Ouvrir le dédouanement"),
    "mark_customs_cleared": _("Dédouanement obtenu"),
    "deliver": _("Marquer livrée"),
    "close": _("Clôturer"),
    "block": _("Bloquer"),
    "unblock": _("Débloquer"),
}

_TRIP_STEPS = {
    LogTrip.STATUS_PLANNED: [NextStep("start", str(_("Démarrer la tournée")))],
    LogTrip.STATUS_IN_PROGRESS: [NextStep("close", str(_("Clôturer la tournée")))],
}


def _shipment_steps(instance: Any, user: User) -> list[NextStep]:
    return fsm_next_steps(
        instance,
        user,
        field_name="state",
        write_codename=_SHIPMENT_WRITE,
        labels={code: str(libelle) for code, libelle in _SHIPMENT_LABELS.items()},
    )


def _trip_steps(instance: Any, user: User) -> list[NextStep]:
    return declared_next_steps(
        instance,
        user,
        state_field="status",
        write_codename=_TRIP_WRITE,
        par_etat=_TRIP_STEPS,
    )


def register() -> None:
    register_next_steps("logistics.LogShipment", _shipment_steps)
    register_next_steps("logistics.LogTrip", _trip_steps)
