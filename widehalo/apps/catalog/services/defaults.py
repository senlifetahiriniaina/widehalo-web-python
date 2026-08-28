"""Entite variante placeholder — chantier RG-QUALIF (qualification et
identification universelle des donnees importees). Un import qui
reference une variante produit par un code non reconnu ne doit jamais
bloquer la ligne : la materialisation immediate se rabat sur une variante
generique "a qualifier" (sous une categorie/gamme "Non classe" dediees),
et la ligne d'import qui l'utilise reste marquee `needs_qualification`
jusqu'a remplacement par la vraie variante."""

from __future__ import annotations

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.catalog.models import Category, ProductTemplate, ProductVariant, UnitOfMeasure
from apps.core.models.tenant import Tenant
from apps.core.services.sequences import next_reference

_UNCLASSIFIED_CATEGORY_NAME = "Non classé"
_PLACEHOLDER_TEMPLATE_NAME = "Produit à qualifier"
_PLACEHOLDER_UOM_CODE = "PLC"


def _ensure_placeholder_uom(tenant: Tenant) -> UnitOfMeasure:
    uom = UnitOfMeasure.objects.filter(tenant=tenant, code=_PLACEHOLDER_UOM_CODE).first()
    if uom is not None:
        return uom
    return UnitOfMeasure.objects.create(
        tenant=tenant,
        code=_PLACEHOLDER_UOM_CODE,
        name=str(_("Unité à qualifier")),
        category=UnitOfMeasure.CATEGORY_COUNT,
        is_base=True,
    )


def _ensure_unclassified_category(tenant: Tenant) -> Category:
    category = Category.objects.filter(tenant=tenant, name=_UNCLASSIFIED_CATEGORY_NAME).first()
    if category is not None:
        return category
    return Category.objects.create(tenant=tenant, name=_UNCLASSIFIED_CATEGORY_NAME)


def ensure_default_variant(tenant: Tenant) -> ProductVariant:
    """Cree, s'il n'existe pas encore, LA variante placeholder de ce tenant
    (get-or-create idempotent — un seul appel produit un seul placeholder,
    tout appel suivant renvoie le meme enregistrement). Un produit
    generique unique suffit (contrairement a `partners`, un import ne
    distingue pas plusieurs "roles" de produit) : la categorie/gamme
    "Non classé" et le template "Produit à qualifier" sont eux aussi
    crees/reutilises au besoin."""
    existing = ProductVariant.objects.filter(tenant=tenant, is_placeholder=True).first()
    if existing is not None:
        return existing

    category = _ensure_unclassified_category(tenant)
    uom = _ensure_placeholder_uom(tenant)
    template = ProductTemplate.objects.filter(
        tenant=tenant, name=_PLACEHOLDER_TEMPLATE_NAME
    ).first()
    if template is None:
        template = ProductTemplate.objects.create(
            tenant=tenant,
            reference=next_reference(tenant, "TPLPLC", timezone.now().year),
            name=str(_PLACEHOLDER_TEMPLATE_NAME),
            category=category,
            base_uom=uom,
        )

    return ProductVariant.objects.create(
        tenant=tenant,
        reference=next_reference(tenant, "VARPLC", timezone.now().year),
        template=template,
        is_placeholder=True,
    )
