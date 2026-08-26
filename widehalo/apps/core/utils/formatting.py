"""Formatage localise des montants et des dates. Regle normative : les
montants sont TOUJOURS stockes en DecimalField(18,4) — cette fonction ne
change jamais la valeur stockee, seulement sa representation textuelle."""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

DISPLAY_TIMEZONE = ZoneInfo(getattr(settings, "DISPLAY_TIME_ZONE", "Indian/Antananarivo"))


def format_mga(amount: Decimal) -> str:
    """Affiche un montant en Ariary sans decimale (convention monetaire
    malgache), avec separateur de milliers par espace insecable."""
    rounded = amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    formatted = f"{rounded:,}".replace(",", " ")
    return f"{formatted} Ar"


def to_display_timezone(value: datetime) -> datetime:
    """Convertit un datetime (stocke en UTC) vers le fuseau d'affichage
    Indian/Antananarivo, sans jamais modifier le stockage en base."""
    return timezone.localtime(value, timezone=DISPLAY_TIMEZONE)
