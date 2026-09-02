"""Contrat public de l'app `catalog` — seule surface que les autres apps
metier ont le droit d'importer (cf. tests/architecture/test_module_boundaries.py)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.catalog.models import (
    CatalogCertification,
    Packaging,
    ProductSupplierInfo,
    ProductVariant,
    TextileSpec,
)
from apps.catalog.services import defaults as _defaults
from apps.catalog.services.pricing import get_price
from apps.catalog.services.textile import length_from_weight_kg, weight_kg_from_length
from apps.core.models.tenant import Tenant


def get_variant_price(variant_id: Any, *, partner_id: Any = None) -> Decimal:
    variant = ProductVariant.objects.get(id=variant_id)
    return get_price(variant, partner_id=partner_id)


def get_variant_reference(variant_id: Any) -> str:
    variant = ProductVariant.objects.filter(id=variant_id).first()
    return variant.reference if variant is not None else ""


def get_variant_id_by_reference(reference: str) -> UUID | None:
    """Sens inverse de `get_variant_reference` — necessaire a
    `stocks.services.stock_import` pour resoudre la colonne `variant_code`
    d'un import de quantites initiales vers l'UUID de variante attendu par
    `stocks` (jamais de FK Django vers `catalog`, regle de couplage n°1).
    Retourne `None`, jamais une exception, si aucune variante ne porte
    cette reference pour le tenant courant (RLS deja actif) — meme
    discipline que `get_variant_template_id`."""
    variant = ProductVariant.objects.filter(reference=reference).first()
    if variant is None:
        return None
    variant_id: UUID = variant.id
    return variant_id


def is_variant_sellable(variant_id: Any) -> bool:
    """Le catalogue est organise en parent (`ProductTemplate`, porteur de
    `is_sellable`) / fils (`ProductVariant`) — un module metier qui
    resout une ligne de devis/facture/commande depuis un `variant_id`
    doit toujours revalider ce champ COTE SERVEUR avant de creer la
    ligne (jamais se fier uniquement au filtrage du selecteur cote
    ecran, qui reste contournable par un POST direct). Retourne `False`,
    jamais une exception, si la variante n'existe pas — un `variant_id`
    inconnu n'est de toute facon jamais vendable."""
    variant = ProductVariant.objects.filter(id=variant_id).select_related("template").first()
    if variant is None:
        return False
    is_sellable: bool = variant.template.is_sellable
    return is_sellable


def list_sellable_variants() -> list[dict[str, Any]]:
    """Alimente les selecteurs de produit des ecrans de devis/facture/
    commande (`sales`/`accounting`) — ne renvoie QUE les variantes dont le
    `ProductTemplate` parent est marque `is_sellable=True` (jamais un
    composant/matiere interne, ex. les "trims" de la fixture de
    demonstration). Primitives uniquement (jamais l'objet ORM, regle de
    couplage n°1)."""
    variants = ProductVariant.objects.filter(
        is_active=True, template__is_sellable=True, template__is_active=True
    ).select_related("template")
    return [
        {
            "id": str(variant.id),
            "reference": variant.reference,
            "label": f"{variant.reference} — {variant.template.name}",
        }
        for variant in variants
    ]


def ensure_default_variant(tenant: Tenant) -> UUID:
    """Enveloppe publique de `apps.catalog.services.defaults.
    ensure_default_variant` — seule surface autorisee pour un autre module
    metier (`stocks`, `accounting`...) qui a besoin de rattacher une ligne
    d'import a une variante placeholder (chantier RG-QUALIF). Retourne
    l'UUID, jamais l'objet `ProductVariant` (regle de couplage n°1)."""
    variant_id: UUID = _defaults.ensure_default_variant(tenant).id
    return variant_id


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


def list_supplier_products(partner_id: Any, *, limit: int = 20) -> list[dict[str, Any]]:
    """Gap PT5 du chantier "fiche partenaire a onglets par role" (cf.
    plan) : alimente l'onglet "Fournisseur (achat)" de la fiche
    partenaire avec les lignes `ProductSupplierInfo` de ce fournisseur —
    `partners` ne doit jamais importer `apps.catalog.models` (regle de
    couplage n°1).

    Retourne des dicts primitifs `{"variant_id", "variant_reference",
    "product_name", "supplier_reference", "price_mga", "lead_time_days"}`,
    jamais l'objet `ProductSupplierInfo`, tries par reference de variante
    croissante pour un affichage stable — meme discipline que
    `select_preferred_supplier`. Liste vide, jamais d'exception, si aucune
    ligne ne correspond a ce `partner_id`."""
    infos = (
        ProductSupplierInfo.objects.filter(partner_id=partner_id)
        .select_related("variant", "variant__template")
        .order_by("variant__reference")[:limit]
    )
    return [
        {
            "variant_id": info.variant_id,
            "variant_reference": info.variant.reference,
            "product_name": info.variant.template.name,
            "supplier_reference": info.supplier_reference,
            "price_mga": info.price_mga,
            "lead_time_days": info.lead_time_days,
        }
        for info in infos
    ]


def set_supplier_priority(
    partner_id: Any, *, priority: int, variant_ids: list[Any] | None = None
) -> int:
    """RG-PUR-8 (gap PU7 du sous-sequencement `purchase`, cf. plan) : met a
    jour `ProductSupplierInfo.priority` pour TOUTES les lignes de ce
    fournisseur (`partner_id`), optionnellement restreintes a
    `variant_ids`. Point d'entree unique pour
    `purchase.services.evaluation.apply_score_to_priority` — `purchase` ne
    doit jamais manipuler `ProductSupplierInfo` directement (regle de
    couplage n°1).

    Retourne le nombre de lignes mises a jour (`0` si aucune ligne ne
    correspond, jamais une exception)."""
    queryset = ProductSupplierInfo.objects.filter(partner_id=partner_id)
    if variant_ids is not None:
        queryset = queryset.filter(variant_id__in=variant_ids)
    return queryset.update(priority=priority)


def convert_textile_measurement(
    variant_id: Any, *, length_m: Decimal | None = None, weight_kg: Decimal | None = None
) -> dict[str, Decimal] | None:
    """Gap ajoute pour ST3 de `stocks` (RG-STK-5, cf. plan) : convertit une
    mesure poids <-> longueur pour une variante textile a partir de son
    `TextileSpec` (grammage/laize), resolu ICI et jamais transmis a
    l'appelant — `stocks` ne doit jamais manipuler un objet `TextileSpec`
    ni `ProductVariant` (regle de couplage n°1). Retourne les DEUX valeurs
    (`length_m` et `weight_kg`), celle fournie par l'appelant renvoyee
    telle quelle, l'autre calculee via `apps.catalog.services.textile`
    (jamais de duplication de la formule de conversion dans `stocks`).

    Exactement un des deux parametres doit etre fourni (`ValidationError`
    i18n sinon — les deux a la fois ou aucun des deux n'a de sens pour une
    conversion).

    Retourne `None`, jamais une exception, si la variante n'existe pas, si
    elle n'a pas de `TextileSpec`, ou si ce `TextileSpec` n'a pas les
    dimensions necessaires (grammage/laize) — meme discipline "ne jamais
    lever sur une simple absence de donnee" que `get_supplier_lead_time_days`
    ci-dessus. `apps.catalog.services.textile._require_dimensions` leve une
    `ValidationError` dans ce dernier cas precis : capturee ici plutot que
    laissee se propager, pour ne pas exposer ce type d'exception a
    l'appelant pour un cas qui n'est, de son point de vue, qu'une donnee
    indisponible."""
    if (length_m is None) == (weight_kg is None):
        raise ValidationError(
            _(
                "Fournir exactement une mesure a convertir : soit la longueur (m), "
                "soit le poids (kg), jamais les deux ni aucune des deux."
            )
        )
    variant = ProductVariant.objects.filter(id=variant_id).first()
    if variant is None:
        return None
    spec = TextileSpec.objects.filter(variant=variant).first()
    if spec is None:
        return None
    try:
        if length_m is not None:
            weight_kg = weight_kg_from_length(spec, length_m)
        else:
            # Garanti non-`None` par la garde XOR ci-dessus (exactement un
            # des deux est fourni) — assertion uniquement pour le
            # narrowing mypy, jamais atteignable en pratique.
            assert weight_kg is not None
            length_m = length_from_weight_kg(spec, weight_kg)
    except ValidationError:
        return None
    return {"length_m": length_m, "weight_kg": weight_kg}


def get_variant_packaging(variant_id: Any) -> dict[str, Any] | None:
    """Gap ajoute pour LOG3 de `logistics` (RG-LOG-5, cf. plan) : conditionnement
    (`catalog_packaging`) declare pour une variante — combien d'unites tiennent
    dans un colis (`unit_count`) et dans quelle unite (`uom.code`). Retourne le
    PREMIER conditionnement connu de la variante (une variante peut en
    declarer plusieurs — pas de notion de conditionnement "par defaut"
    explicite aujourd'hui, simplification documentee) ou `None`, jamais une
    exception, si la variante n'existe pas ou n'a aucun conditionnement
    declare (meme discipline que `get_supplier_lead_time_days`)."""
    packaging = Packaging.objects.filter(variant_id=variant_id).select_related("uom").first()
    if packaging is None:
        return None
    return {"unit_count": packaging.unit_count, "uom_code": packaging.uom.code}


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
