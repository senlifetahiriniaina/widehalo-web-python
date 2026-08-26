"""Contrat public de l'app `catalog` — seule surface que les autres apps
metier ont le droit d'importer (cf. tests/architecture/test_module_boundaries.py)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.catalog.models import ProductVariant
from apps.catalog.services.pricing import get_price


def get_variant_price(variant_id: Any, *, partner_id: Any = None) -> Decimal:
    variant = ProductVariant.objects.get(id=variant_id)
    return get_price(variant, partner_id=partner_id)


def get_variant_reference(variant_id: Any) -> str:
    variant = ProductVariant.objects.filter(id=variant_id).first()
    return variant.reference if variant is not None else ""
