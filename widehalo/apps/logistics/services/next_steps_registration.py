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
from apps.core.services.presentation import (
    COLONNE_BLOQUE,
    COLONNE_EN_ATTENTE,
    COLONNE_EN_COURS,
    COLONNE_SANS_SUITE,
    COLONNE_TERMINE,
    Board,
    LigneResume,
    register_board,
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


#: C-4 — les six etats intermediaires d'une expedition (reservee, enlevee,
#: en transit, au port, en dedouanement, dedouanee) decrivent UN convoyage
#: en cours. Ils font une colonne ; l'etat exact reste lu sur la carte.
_SHIPMENT_BOARD = Board(
    state_field="state",
    par_etat={
        "planned": COLONNE_EN_ATTENTE,
        "booked": COLONNE_EN_COURS,
        "picked_up": COLONNE_EN_COURS,
        "in_transit": COLONNE_EN_COURS,
        "arrived_at_port": COLONNE_EN_COURS,
        "customs_clearance": COLONNE_EN_COURS,
        "customs_cleared": COLONNE_EN_COURS,
        "delivered": COLONNE_TERMINE,
        "closed": COLONNE_TERMINE,
        "blocked": COLONNE_BLOQUE,
    },
    resume=(
        LigneResume(label=_("Origine"), attribut="origin"),
        LigneResume(label=_("Destination"), attribut="destination"),
        LigneResume(label=_("Transporteur"), attribut="carrier"),
    ),
    fiche=(
        LigneResume(label=_("Référence"), attribut="reference"),
        LigneResume(label=_("Origine"), attribut="origin"),
        LigneResume(label=_("Destination"), attribut="destination"),
        LigneResume(label=_("Transporteur"), attribut="carrier"),
        LigneResume(label=_("Incoterm"), attribut="incoterm"),
        LigneResume(label=_("État"), attribut="state"),
    ),
)

#: `LogTrip` porte DEJA le vocabulaire demande — planifie / en cours /
#: termine / annule. Sa projection est donc l'identite, et c'est elle qui a
#: servi de reference aux quatre autres.
_TRIP_BOARD = Board(
    state_field="status",
    par_etat={
        "planned": COLONNE_EN_ATTENTE,
        "in_progress": COLONNE_EN_COURS,
        "completed": COLONNE_TERMINE,
        "cancelled": COLONNE_SANS_SUITE,
    },
    resume=(
        LigneResume(label=_("Véhicule"), attribut="vehicle"),
        LigneResume(label=_("Chauffeur"), attribut="driver"),
        LigneResume(label=_("Date"), attribut="date"),
    ),
    fiche=(
        LigneResume(label=_("Référence"), attribut="reference"),
        LigneResume(label=_("Véhicule"), attribut="vehicle"),
        LigneResume(label=_("Chauffeur"), attribut="driver"),
        LigneResume(label=_("Date"), attribut="date"),
        LigneResume(label=_("Kilométrage au départ"), attribut="start_odometer_km"),
        LigneResume(label=_("Kilométrage à l'arrivée"), attribut="end_odometer_km"),
        LigneResume(label=_("Statut"), attribut="status"),
    ),
)


def register() -> None:
    register_next_steps("logistics.LogShipment", _shipment_steps)
    register_next_steps("logistics.LogTrip", _trip_steps)
    register_board("logistics.LogShipment", _SHIPMENT_BOARD)
    register_board("logistics.LogTrip", _TRIP_BOARD)
