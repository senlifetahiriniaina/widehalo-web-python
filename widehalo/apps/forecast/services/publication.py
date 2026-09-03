"""Publication (FOR-10 : « prévision publiée disponible comme scénario de
référence dans la simulation financière, avec version et date »). Un
instantané `ForPublication` est immuable une fois créé (même discipline
que `SimBaseline`) — la prévision continue d'évoluer en base (nouveaux
calculs, ajustements) sans jamais modifier une publication déjà émise."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Max
from django.utils import timezone

from apps.forecast.models import ForPublication, ForSeriesForecast

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User


def publish(tenant: Tenant, *, user: User | None) -> ForPublication:
    """Fige l'état courant de TOUTES les prévisions de `tenant` (valeur
    retenue = `final_value`, ajustée si présente sinon statistique)."""
    forecasts = list(ForSeriesForecast.objects.filter(tenant=tenant).order_by("period"))
    snapshot = [
        {
            "dimension_type": f.dimension_type,
            "dimension_value": f.dimension_value,
            "period": f.period.isoformat(),
            "value": str(f.final_value),
        }
        for f in forecasts
    ]
    last_version = (
        ForPublication.objects.filter(tenant=tenant).aggregate(m=Max("version"))["m"] or 0
    )
    periods = [f.period for f in forecasts]
    return ForPublication.objects.create(
        tenant=tenant,
        version=last_version + 1,
        published_at=timezone.now(),
        published_by=user,
        period_start=min(periods) if periods else timezone.now().date(),
        period_end=max(periods) if periods else timezone.now().date(),
        snapshot=snapshot,
    )


def get_latest_publication(tenant: Tenant) -> ForPublication | None:
    return ForPublication.objects.filter(tenant=tenant).order_by("-version").first()
