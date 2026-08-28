"""RG-PRS-2 : retention 30 jours de la geolocalisation precise. Meme
discipline que `apps.core.services.sandbox.purge_expired_sandboxes()` —
callable synchrone, jamais un cron auto-enregistre (invoque par une
commande de management dediee, PR6)."""

from __future__ import annotations

import datetime as dt

from django.utils import timezone

from apps.presence.models import PrsAttendance

RETENTION_DAYS = 30


def purge_expired_geolocation() -> int:
    """Efface `latitude`/`longitude` des pointages captures il y a plus de
    `RETENTION_DAYS` jours, en conservant `within_perimeter` (seul le
    resultat booleen "dans le perimetre" survit au-dela de 30 jours,
    RG-PRS-2). Retourne le nombre de pointages purges."""
    cutoff = timezone.now() - dt.timedelta(days=RETENTION_DAYS)
    queryset = PrsAttendance.all_objects.filter(geo_captured_at__lte=cutoff, latitude__isnull=False)
    count = queryset.update(latitude=None, longitude=None)
    return count
