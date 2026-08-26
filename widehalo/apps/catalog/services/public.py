"""Contrat public de l'app `catalog` — seule surface que les autres apps
metier ont le droit d'importer (cf. tests/architecture/test_module_boundaries.py)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from django.utils import timezone

from apps.catalog.models import CatalogCertification, ProductVariant
from apps.catalog.services.pricing import get_price


def get_variant_price(variant_id: Any, *, partner_id: Any = None) -> Decimal:
    variant = ProductVariant.objects.get(id=variant_id)
    return get_price(variant, partner_id=partner_id)


def get_variant_reference(variant_id: Any) -> str:
    variant = ProductVariant.objects.filter(id=variant_id).first()
    return variant.reference if variant is not None else ""


def get_valid_certifications(variant_id: Any, *, on_date: dt.date | None = None) -> list[str]:
    """CAT-NORM1 : codes de normes valides a `on_date` (aujourd'hui par
    defaut) pour une variante — utilise par `mrp` pour le controle de
    conformite bloquant (MRP-QQCD1)."""
    on_date = on_date or timezone.now().date()
    certifications = CatalogCertification.objects.filter(variant_id=variant_id).select_related(
        "standard"
    )
    valid_codes = []
    for certification in certifications:
        if certification.valid_from and certification.valid_from > on_date:
            continue
        if certification.valid_until and certification.valid_until < on_date:
            continue
        valid_codes.append(certification.standard.code)
    return valid_codes
