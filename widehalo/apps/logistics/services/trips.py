"""LOG2 : trajets/arrets. RG-LOG-2 (kilometrage alimente le compteur
vehicule a la cloture), RG-LOG-3 (preuve de livraison), RG-LOG-4/LOG-TOUR1
(suggestion d'ordre des arrets par plus-proche-voisin — jamais un
ordonnancement impose, toujours modifiable manuellement via
`reorder_stops`), LOG-GEO1 (consentement explicite requis avant tout
enregistrement de position, masquage de l'affichage hors heures de
travail), LOG-REC1 (tournees recurrentes).

`suggest_stop_order()` est une fonction pure (aucun acces base) : le CDC
lui-meme ecarte l'optimisation automatique complete (2-opt) de la V1 mais
adopte partiellement l'enrichissement WideHalo — plus-proche-voisin,
implementable simplement, gain reel des 4 arrets. Le point de depart est le
premier arret de la liste passee (l'appelant decide de l'ordre initial, ex.
l'ordre de saisie) ; les arrets sans coordonnees ne sont jamais reordonnes
par proximite (ils restent a leur position relative, la seule information
disponible pour eux est l'ordre de saisie)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.utils.translation import gettext as _

from apps.core.services.documents import store_document
from apps.core.services.sequences import next_reference
from apps.core.utils.formatting import to_display_timezone
from apps.logistics.models import LogTrip, LogTripStop, LogTripTemplate
from apps.logistics.services.vehicles import record_vehicle_cost

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User
    from apps.logistics.models import LogDriver, LogVehicle

# LOG-GEO1 : fenetre horaire par defaut au-dela de laquelle la position
# d'un arret n'est plus exposee (masquage a l'affichage, pas a la
# collecte) — parametrable par appel, ce n'est pas une regle metier figee.
DEFAULT_WORK_HOURS_START = 6
DEFAULT_WORK_HOURS_END = 20


def create_trip(
    tenant: Tenant,
    *,
    vehicle: LogVehicle,
    driver: LogDriver,
    date: dt.date,
    stops: list[dict[str, Any]],
) -> LogTrip:
    """`stops` : liste de dicts `{address, type=..., latitude=None,
    longitude=None, planned_time=None}`, dans l'ordre de saisie — l'ordre
    initial des `LogTripStop` crees correspond exactement a cet ordre
    (aucun reordonnancement automatique implicite, cf. `suggest_stop_order`
    pour une suggestion explicite separee)."""
    if not stops:
        raise ValidationError(_("Un trajet doit comporter au moins un arret."))

    trip = LogTrip(
        tenant=tenant,
        vehicle=vehicle,
        driver=driver,
        date=date,
        reference=next_reference(tenant, "TRJ", date.year),
    )
    trip.full_clean()
    trip.save()

    for index, stop_data in enumerate(stops, start=1):
        stop = LogTripStop(
            tenant=tenant,
            trip=trip,
            sequence=index,
            type=stop_data.get("type", LogTripStop.TYPE_DROPOFF),
            address=stop_data["address"],
            latitude=stop_data.get("latitude"),
            longitude=stop_data.get("longitude"),
            planned_time=stop_data.get("planned_time"),
        )
        stop.full_clean()
        stop.save()

    return trip


def suggest_stop_order(
    stops: list[dict[str, Any]],
) -> list[int]:
    """RG-LOG-4/LOG-TOUR1 : renvoie les INDEX (dans `stops`) d'un ordre de
    visite suggere par plus-proche-voisin a partir du premier element de la
    liste. Fonction pure, ne modifie ni ne persiste rien — c'est a
    l'appelant de decider s'il applique la suggestion (`reorder_stops`) ou
    la modifie manuellement avant. Un arret sans coordonnees garde sa
    position relative d'origine, ajoute a la fin de la tournee suggeree."""
    with_coords = [
        i
        for i, s in enumerate(stops)
        if s.get("latitude") is not None and s.get("longitude") is not None
    ]
    without_coords = [i for i in range(len(stops)) if i not in with_coords]

    if len(with_coords) <= 1:
        return with_coords + without_coords

    remaining = list(with_coords)
    order = [remaining.pop(0)]

    def _distance_sq(a: int, b: int) -> Decimal:
        dx = Decimal(stops[a]["latitude"]) - Decimal(stops[b]["latitude"])
        dy = Decimal(stops[a]["longitude"]) - Decimal(stops[b]["longitude"])
        return dx * dx + dy * dy

    while remaining:
        current = order[-1]
        nearest = min(remaining, key=lambda candidate: _distance_sq(current, candidate))
        order.append(nearest)
        remaining.remove(nearest)

    return order + without_coords


def reorder_stops(trip: LogTrip, ordered_stop_ids: list[Any]) -> None:
    """Applique un nouvel ordre explicite (suggere ou choisi a la main) —
    toujours une action explicite de l'appelant, jamais automatique a la
    creation du trajet."""
    stops_by_id = {stop.id: stop for stop in trip.stops.all()}
    if set(stops_by_id) != set(ordered_stop_ids):
        raise ValidationError(
            _("La nouvelle liste d'arrets doit contenir exactement les arrets existants du trajet.")
        )
    # Deux passes pour eviter toute collision transitoire sur la contrainte
    # UNIQUE (trip, sequence) : d'abord des valeurs hors plage, puis les
    # valeurs finales.
    offset = len(ordered_stop_ids) + 1
    for position, stop_id in enumerate(ordered_stop_ids, start=1):
        LogTripStop.objects.filter(id=stop_id).update(sequence=offset + position)
    for position, stop_id in enumerate(ordered_stop_ids, start=1):
        LogTripStop.objects.filter(id=stop_id).update(sequence=position)


def record_stop_completion(
    stop: LogTripStop,
    *,
    actual_time: dt.datetime,
    latitude: Decimal | None = None,
    longitude: Decimal | None = None,
    proof_file: UploadedFile[Any] | None = None,
    signed_by: str = "",
    uploaded_by: User | None = None,
) -> LogTripStop:
    """RG-LOG-3 (preuve de livraison) + LOG-GEO1 (consentement) : une
    position n'est enregistree QUE si le chauffeur du trajet a
    explicitement consenti (`LogDriver.consent_geolocation`) — sinon
    `latitude`/`longitude` sont ignores (jamais stockes malgre eux), pas
    une erreur bloquante (l'arret reste completable sans position)."""
    driver = stop.trip.driver
    if (latitude is not None or longitude is not None) and not driver.consent_geolocation:
        latitude = None
        longitude = None

    if proof_file is not None:
        document = store_document(
            tenant=stop.tenant,
            uploaded_file=proof_file,
            uploaded_by=uploaded_by,
            content_object=stop,
        )
        stop.proof_document = document

    stop.actual_time = actual_time
    stop.latitude = latitude
    stop.longitude = longitude
    stop.signed_by = signed_by
    stop.status = LogTripStop.STATUS_COMPLETED
    stop.full_clean()
    stop.save()
    return stop


def get_stop_location(
    stop: LogTripStop,
    *,
    work_hours_start: int = DEFAULT_WORK_HOURS_START,
    work_hours_end: int = DEFAULT_WORK_HOURS_END,
) -> tuple[Decimal, Decimal] | None:
    """LOG-GEO1 : masque la position hors heures de travail — renvoie
    `None` si `actual_time` tombe hors de la fenetre `[work_hours_start,
    work_hours_end)`, si aucune position n'a ete enregistree, ou si l'arret
    n'a pas encore de `actual_time` (pas encore visite). Masquage a la
    LECTURE, pas a l'ecriture : la donnee reste en base (necessaire pour la
    tracabilite du trajet), seule son exposition est restreinte."""
    if stop.latitude is None or stop.longitude is None or stop.actual_time is None:
        return None
    local_hour = to_display_timezone(stop.actual_time).hour
    if not (work_hours_start <= local_hour < work_hours_end):
        return None
    return stop.latitude, stop.longitude


def close_trip(trip: LogTrip, *, end_odometer_km: Decimal) -> LogTrip:
    """RG-LOG-2 : cloture le trajet, alimente le compteur du vehicule.
    Refuse un kilometrage de fin inferieur au depart (erreur de saisie) ou
    l'absence de kilometrage de depart (jamais devine)."""
    if trip.start_odometer_km is None:
        raise ValidationError(_("Kilometrage de depart manquant — a saisir avant la cloture."))
    if end_odometer_km < trip.start_odometer_km:
        raise ValidationError(
            _("Le kilometrage de fin ne peut pas etre inferieur au kilometrage de depart.")
        )

    trip.end_odometer_km = end_odometer_km
    trip.status = LogTrip.STATUS_COMPLETED
    trip.full_clean()
    trip.save(update_fields=["end_odometer_km", "status"])

    vehicle = trip.vehicle
    if end_odometer_km > vehicle.odometer_km:
        vehicle.odometer_km = end_odometer_km
        vehicle.save(update_fields=["odometer_km"])

    return trip


def start_trip(trip: LogTrip, *, start_odometer_km: Decimal) -> LogTrip:
    trip.start_odometer_km = start_odometer_km
    trip.status = LogTrip.STATUS_IN_PROGRESS
    trip.full_clean()
    trip.save(update_fields=["start_odometer_km", "status"])
    return trip


def record_trip_fuel_cost(trip: LogTrip, *, amount_mga: Decimal, note: str = "") -> None:
    """Convenance : un cout carburant lie a un trajet reste un
    `LogVehicleCost` ordinaire (`services/vehicles.py`), rattache au
    vehicule du trajet — pas une nouvelle entite dediee."""
    record_vehicle_cost(
        trip.vehicle,
        date=trip.date,
        cost_type="fuel",
        amount_mga=amount_mga,
        note=note or f"Trajet {trip.reference}",
    )


def create_trip_template(
    tenant: Tenant,
    *,
    name: str,
    vehicle: LogVehicle,
    driver: LogDriver,
    interval: str,
    stops_data: list[dict[str, Any]],
    start_date: dt.date,
    end_date: dt.date | None = None,
) -> LogTripTemplate:
    template = LogTripTemplate(
        tenant=tenant,
        name=name,
        vehicle=vehicle,
        driver=driver,
        interval=interval,
        stops_data=stops_data,
        next_run=start_date,
        end_date=end_date,
    )
    template.full_clean()
    template.save()
    return template


_INTERVAL_DAYS: dict[str, int] = {
    LogTripTemplate.INTERVAL_WEEKLY: 7,
    LogTripTemplate.INTERVAL_MONTHLY: 30,
}


def generate_due_trip(template: LogTripTemplate, today: dt.date | None = None) -> LogTrip | None:
    """LOG-REC1 : genere le trajet a echeance a partir du gabarit, TOUJOURS
    en `planned` (jamais demarre/confirme automatiquement). Renvoie `None`
    (jamais une exception) quand rien n'est a generer — pas encore a
    echeance, ou gabarit echu (`end_date` depassee) : ce sont des cas
    normaux."""
    if today is None:
        today = dt.date.today()
    if not template.is_active:
        return None
    if template.next_run > today:
        return None
    if template.end_date is not None and template.next_run > template.end_date:
        return None

    trip = create_trip(
        template.tenant,
        vehicle=template.vehicle,
        driver=template.driver,
        date=template.next_run,
        stops=template.stops_data,
    )
    trip.template = template
    trip.save(update_fields=["template"])

    template.next_run = template.next_run + dt.timedelta(days=_INTERVAL_DAYS[template.interval])
    template.save(update_fields=["next_run"])
    return trip
