"""Contrat public de l'app `catalog` — seule surface que les autres apps
metier ont le droit d'importer (cf. tests/architecture/test_module_boundaries.py)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.utils import timezone

from apps.catalog.models import CatalogCertification, ProductSupplierInfo, ProductVariant
from apps.catalog.services.pricing import get_price


def get_variant_price(variant_id: Any, *, partner_id: Any = None) -> Decimal:
    variant = ProductVariant.objects.get(id=variant_id)
    return get_price(variant, partner_id=partner_id)


def get_variant_reference(variant_id: Any) -> str:
    variant = ProductVariant.objects.filter(id=variant_id).first()
    return variant.reference if variant is not None else ""


def get_variant_template_id(variant_id: Any) -> UUID | None:
    """Gap identifie par le sous-sequencement S3 de `sales` (RG-SAL-3) :
    remonte le `ProductTemplate` d'une variante — necessaire a
    `sales.services.procurement` pour passer du `variant_id` stocke sur
    une ligne de commande au `product_template_id` qu'attend
    `mrp.services.public.list_active_boms_for_product`/
    `create_manufacturing_order`. Retourne `None`, jamais une exception,
    si la variante n'existe pas (meme discipline que `get_variant_reference`)."""
    variant = ProductVariant.objects.filter(id=variant_id).first()
    if variant is None:
        return None
    template_id: UUID = variant.template_id
    return template_id


def get_supplier_lead_time_days(variant_id: Any, *, partner_id: Any = None) -> int | None:
    """RG-SAL-7 (composante "delais fournisseurs", cf. plan
    sous-sequencement `sales` S6) : delai fournisseur le plus court connu
    pour le produit d'une variante (`ProductSupplierInfo`, cherchee sur
    tout le `ProductTemplate` de la variante — un fournisseur reference
    generalement le produit, pas chaque variante taille/couleur
    individuellement).

    `partner_id` optionnel restreint a un fournisseur precis (retourne
    alors son `lead_time_days` s'il existe). Sans `partner_id`, retourne
    le minimum parmi tous les fournisseurs connus du produit (l'hypothese
    la plus optimiste disponible, coherente avec l'usage "delai avant
    rupture" de RG-SAL-7 — un acheteur choisirait le fournisseur le plus
    rapide s'il devait commander en urgence).

    Retourne `None`, jamais une exception, si la variante n'existe pas ou
    qu'aucune information fournisseur n'est enregistree pour son produit
    (meme discipline que `get_variant_template_id`)."""
    variant = ProductVariant.objects.filter(id=variant_id).first()
    if variant is None:
        return None

    infos = ProductSupplierInfo.objects.filter(variant__template_id=variant.template_id)
    if partner_id is not None:
        infos = infos.filter(partner_id=partner_id)

    lead_time = infos.order_by("lead_time_days").values_list("lead_time_days", flat=True).first()
    return lead_time


def select_preferred_supplier(variant_id: Any) -> dict[str, Any] | None:
    """RG-PUR-1 (gap PU2 du sous-sequencement `purchase`, cf. plan) :
    fournisseur retenu pour le produit d'une variante, cherche sur tout le
    `ProductTemplate` de la variante (meme portee que
    `get_supplier_lead_time_days` — un fournisseur reference generalement
    le produit, pas chaque variante taille/couleur individuellement).

    Ordre de selection impose par le CDC : `priority` (croissant, plus bas
    = plus prioritaire) puis `price_mga` (croissant) puis `lead_time_days`
    (croissant) — le premier `ProductSupplierInfo` de ce tri est retenu.

    Retourne un dict primitif `{"partner_id", "price_mga", "lead_time_days",
    "origin", "min_qty"}`, jamais l'objet `ProductSupplierInfo` (contrat
    public, cf. regle de couplage n°1). Retourne `None`, jamais une
    exception, si la variante n'existe pas ou qu'aucune information
    fournisseur n'est enregistree pour son produit (meme discipline que
    `get_supplier_lead_time_days`)."""
    variant = ProductVariant.objects.filter(id=variant_id).first()
    if variant is None:
        return None

    info = (
        ProductSupplierInfo.objects.filter(variant__template_id=variant.template_id)
        .order_by("priority", "price_mga", "lead_time_days")
        .first()
    )
    if info is None:
        return None

    return {
        "partner_id": info.partner_id,
        "price_mga": info.price_mga,
        "lead_time_days": info.lead_time_days,
        "origin": info.origin,
        "min_qty": info.min_qty,
    }


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
