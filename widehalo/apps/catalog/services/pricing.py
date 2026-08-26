"""Cascade de tarification, du niveau le plus specifique au plus general :
contrat > liste client > liste par defaut > prix catalogue (`base_price_mga`
du template, toujours defini, jamais None — dernier filet)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db.models import Q
from django.utils import timezone

from apps.catalog.models import PriceList, ProductVariant


def _validity_filter(today: Any) -> Q:
    return (Q(valid_from__isnull=True) | Q(valid_from__lte=today)) & (
        Q(valid_to__isnull=True) | Q(valid_to__gte=today)
    )


def _price_from_list(variant: ProductVariant, kind: str, partner_id: Any) -> Decimal | None:
    today = timezone.now().date()
    price_lists = PriceList.objects.filter(kind=kind, partner_id=partner_id).filter(
        _validity_filter(today)
    )
    item = variant.price_items.filter(price_list__in=price_lists).order_by("-created_at").first()
    return item.price_mga if item else None


def get_price(variant: ProductVariant, *, partner_id: Any = None) -> Decimal:
    if partner_id is not None:
        contract_price = _price_from_list(variant, PriceList.KIND_CONTRACT, partner_id)
        if contract_price is not None:
            return contract_price

        client_price = _price_from_list(variant, PriceList.KIND_CLIENT, partner_id)
        if client_price is not None:
            return client_price

    default_price = _price_from_list(variant, PriceList.KIND_DEFAULT, None)
    if default_price is not None:
        return default_price

    return variant.template.base_price_mga
