"""PR1 : pointage multi-modalite (RG-PRS-1), geolocalisation/geofencing
RGPD (RG-PRS-2), travail a distance (RG-PRS-3), calcul du temps (RG-PRS-4).

**Geofencing — simplification disclosed** : aucun modele "site" dedie
n'existe dans ce lot (budget modeles serre a 170/180 a la cloture de
`logistics, cf. `apps/presence/models.py`). Le perimetre (centre + rayon)
est donc un parametre transmis par l'appelant (vue/API), qui le resout
depuis la configuration du tenant (a affiner dans un futur module
Parametrage) plutot qu'un nouveau modele. Coherent avec RG-PRS-2 :
"parametrable par le tenant" — seul l'OU est reporte, jamais le SI/COMMENT
(le calcul booleen "dans le perimetre" est fait ici, uniformement, quel que
soit d'ou viennent les coordonnees du site)."""

from __future__ import annotations

import datetime as dt
import math
from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.presence.models import PrsAttendance, PrsEmployee

if TYPE_CHECKING:
    from apps.core.models.user import User

EARTH_RADIUS_M = 6_371_000


def _within_perimeter(
    *,
    latitude: Decimal,
    longitude: Decimal,
    site_latitude: Decimal,
    site_longitude: Decimal,
    radius_meters: int,
) -> bool:
    """Distance haversine simple — precision suffisante pour un
    geofencing site (pas une navigation), disclosed."""
    lat1, lon1, lat2, lon2 = (
        math.radians(float(latitude)),
        math.radians(float(longitude)),
        math.radians(float(site_latitude)),
        math.radians(float(site_longitude)),
    )
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    distance = 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))
    return distance <= radius_meters


def check_in(
    employee: PrsEmployee,
    *,
    mode: str,
    location: str = PrsAttendance.LOCATION_SITE,
    at: dt.datetime | None = None,
    latitude: Decimal | None = None,
    longitude: Decimal | None = None,
    site_latitude: Decimal | None = None,
    site_longitude: Decimal | None = None,
    radius_meters: int | None = None,
    ip: str = "",
    device: str = "",
    comment: str = "",
) -> PrsAttendance:
    """RG-PRS-1 : un pointage hors perimetre est ENREGISTRE, jamais rejete —
    seulement signale (`within_perimeter=False`), cf. test d'acceptance
    §5.9.8 n°1."""
    moment = at or timezone.now()
    within_perimeter = None
    if latitude is not None and longitude is not None and radius_meters is not None:
        if site_latitude is None or site_longitude is None:
            raise ValidationError(_("Périmètre du site non configure pour ce pointage."))
        within_perimeter = _within_perimeter(
            latitude=latitude,
            longitude=longitude,
            site_latitude=site_latitude,
            site_longitude=site_longitude,
            radius_meters=radius_meters,
        )

    attendance, created = PrsAttendance.objects.get_or_create(
        tenant=employee.tenant,
        employee=employee,
        date=timezone.localtime(moment).date(),
        mode=mode,
        defaults={
            "location": location,
            "ip": ip,
            "device": device,
            "comment": comment,
        },
    )
    if not created and attendance.check_in is not None:
        raise ValidationError(_("Un pointage d'entrée existe déjà pour ce jour et ce mode."))

    attendance.check_in = moment
    attendance.location = location
    if latitude is not None:
        attendance.latitude = latitude
        attendance.longitude = longitude
        attendance.geo_captured_at = moment
    if within_perimeter is not None:
        attendance.within_perimeter = within_perimeter
    attendance.ip = ip or attendance.ip
    attendance.device = device or attendance.device
    attendance.full_clean()
    attendance.save()
    return attendance


def check_out(
    attendance: PrsAttendance,
    *,
    at: dt.datetime | None = None,
    latitude: Decimal | None = None,
    longitude: Decimal | None = None,
) -> PrsAttendance:
    if attendance.check_in is None:
        raise ValidationError(_("Impossible de pointer une sortie sans entrée préalable."))
    moment = at or timezone.now()
    if moment <= attendance.check_in:
        raise ValidationError(_("L'heure de sortie doit être postérieure a l'heure d'entrée."))

    attendance.check_out = moment
    if latitude is not None:
        attendance.latitude = latitude
        attendance.longitude = longitude
        attendance.geo_captured_at = moment
    compute_worked_time(attendance)
    attendance.full_clean()
    attendance.save()
    return attendance


def compute_worked_time(attendance: PrsAttendance) -> PrsAttendance:
    """RG-PRS-4 : temps travaille/retard/depart anticipe/heures sup depuis
    le calendrier de travail avec tolerance. Simplification disclosed : le
    calendrier journalier (`PrsWorkCalendar.days`) ne porte qu'UNE seule
    plage horaire de reference par jour pour ce calcul (la premiere plage
    definie) — un calendrier multi-plages (pause dejeuner longue) reste
    saisissable (donnee brute conservee) mais seule la premiere plage sert
    de reference retard/depart anticipe en V1."""
    if attendance.check_in is None or attendance.check_out is None:
        return attendance

    worked = attendance.check_out - attendance.check_in
    worked_minutes = max(0, int(worked.total_seconds() // 60))
    attendance.worked_minutes = worked_minutes

    calendar = attendance.employee.work_calendar
    late_minutes = 0
    early_leave_minutes = 0
    overtime_minutes = 0
    if calendar is not None:
        weekday = attendance.date.strftime("%a").lower()[:3]
        slots = calendar.days.get(weekday) or []
        tolerance = dt.timedelta(minutes=calendar.tolerance_min)
        if slots:
            expected_start = _combine(attendance.date, slots[0][0])
            expected_end = _combine(attendance.date, slots[-1][-1])
            if attendance.check_in > expected_start + tolerance:
                late_minutes = int((attendance.check_in - expected_start).total_seconds() // 60)
            if attendance.check_out < expected_end - tolerance:
                early_leave_minutes = int(
                    (expected_end - attendance.check_out).total_seconds() // 60
                )
            if attendance.check_out > expected_end:
                overtime_minutes = int((attendance.check_out - expected_end).total_seconds() // 60)

    attendance.late_minutes = late_minutes
    attendance.early_leave_minutes = early_leave_minutes
    attendance.overtime_minutes = overtime_minutes
    return attendance


def _combine(date: dt.date, hhmm: str) -> dt.datetime:
    hour, minute = (int(part) for part in hhmm.split(":"))
    naive = dt.datetime.combine(date, dt.time(hour, minute))
    return timezone.make_aware(naive)


def manual_entry(
    employee: PrsEmployee,
    *,
    date: dt.date,
    check_in: dt.datetime,
    check_out: dt.datetime | None,
    entered_by: User,
    reason: str,
    location: str = PrsAttendance.LOCATION_SITE,
) -> PrsAttendance:
    """RG-PRS-1 mode "manuel" : toujours motive et journalise
    obligatoirement — `reason` est requis (jamais vide)."""
    if not reason.strip():
        raise ValidationError(_("Une saisie manuelle de pointage doit toujours être motivée."))

    attendance = PrsAttendance(
        tenant=employee.tenant,
        employee=employee,
        date=date,
        check_in=check_in,
        check_out=check_out,
        mode=PrsAttendance.MODE_MANUAL,
        location=location,
        comment=reason,
        created_by=entered_by,
    )
    if check_out is not None:
        compute_worked_time(attendance)
    attendance.full_clean()
    attendance.save()
    return attendance
