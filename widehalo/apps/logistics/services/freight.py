"""LOG3 : prestataires de fret et grille tarifaire declarative. Aucun
appel API transporteur reel dans ce lot (le CDC le dit lui-meme,
§5.7.9) — un tarif est saisi manuellement, `compare_freight_tariffs`
se limite a comparer/classer des lignes deja en base."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from apps.logistics.models import LogFreightTariff, LogServiceProvider

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant


def create_service_provider(
    tenant: Tenant,
    *,
    code: str,
    name: str,
    type: str = LogServiceProvider.TYPE_CARRIER,
    contact_phone: str = "",
    contact_email: str = "",
) -> LogServiceProvider:
    provider = LogServiceProvider(
        tenant=tenant,
        code=code,
        name=name,
        type=type,
        contact_phone=contact_phone,
        contact_email=contact_email,
    )
    provider.full_clean()
    provider.save()
    return provider


def create_freight_tariff(
    provider: LogServiceProvider,
    *,
    origin: str,
    destination: str,
    price_mga: Decimal,
    transit_days: int,
    price_per_kg_mga: Decimal | None = None,
    valid_from: dt.date | None = None,
    valid_to: dt.date | None = None,
) -> LogFreightTariff:
    tariff = LogFreightTariff(
        tenant=provider.tenant,
        provider=provider,
        origin=origin,
        destination=destination,
        price_mga=price_mga,
        price_per_kg_mga=price_per_kg_mga,
        transit_days=transit_days,
        valid_from=valid_from,
        valid_to=valid_to,
    )
    tariff.full_clean()
    tariff.save()
    return tariff


def compare_freight_tariffs(
    tenant: Tenant,
    *,
    origin: str,
    destination: str,
    weight_kg: Decimal | None = None,
    on_date: dt.date | None = None,
) -> list[dict[str, Any]]:
    """Renvoie les tarifs valides pour `origin`/`destination` a `on_date`
    (aujourd'hui par defaut), classes par cout total croissant puis delai
    croissant — le premier de la liste est la proposition "meilleure"
    (cout puis delai), jamais imposee : un simple classement, la decision
    reste humaine."""
    if on_date is None:
        on_date = dt.date.today()

    tariffs = LogFreightTariff.objects.filter(
        tenant=tenant, origin=origin, destination=destination
    ).select_related("provider")

    results: list[dict[str, Any]] = []
    for tariff in tariffs:
        if tariff.valid_from and tariff.valid_from > on_date:
            continue
        if tariff.valid_to and tariff.valid_to < on_date:
            continue

        total_cost = tariff.price_mga
        if weight_kg is not None and tariff.price_per_kg_mga is not None:
            total_cost += tariff.price_per_kg_mga * weight_kg

        results.append(
            {
                "tariff_id": tariff.id,
                "provider_id": tariff.provider_id,
                "provider_name": tariff.provider.name,
                "total_cost_mga": total_cost,
                "transit_days": tariff.transit_days,
            }
        )

    results.sort(key=lambda entry: (entry["total_cost_mga"], entry["transit_days"]))
    return results
