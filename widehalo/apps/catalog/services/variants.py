from __future__ import annotations

from itertools import product
from typing import Any

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.catalog.models import (
    MAX_VARIANT_GENERATING_ATTRIBUTES,
    MAX_VARIANTS_PER_TEMPLATE,
    ProductTemplate,
    ProductVariant,
)
from apps.core.services.sequences import next_reference


def set_variant_attributes(template: ProductTemplate, attribute_ids: list[Any]) -> None:
    """Fixe les attributs generateurs de variantes d'un template — refuse
    au-dela de 2 (regle bloquante du cahier des charges, pas une simple
    recommandation)."""
    if len(attribute_ids) > MAX_VARIANT_GENERATING_ATTRIBUTES:
        raise ValidationError(
            _("Au maximum %(max)d attributs generateurs de variantes par gamme.")
            % {"max": MAX_VARIANT_GENERATING_ATTRIBUTES}
        )
    template.variant_attributes.set(attribute_ids)


def generate_variants(template: ProductTemplate) -> list[ProductVariant]:
    """Genere le produit cartesien des valeurs des attributs generateurs de
    variantes du template. Refuse au-dela de 50 combinaisons (seuil
    bloquant du cahier des charges) — AUCUNE variante n'est creee si le
    total depasse le seuil (tout ou rien, comme l'import de donnees)."""
    from django.utils import timezone

    attributes = list(template.variant_attributes.all())
    value_lists = [list(attribute.values.all()) for attribute in attributes]
    combinations = list(product(*value_lists)) if value_lists else []

    if len(combinations) > MAX_VARIANTS_PER_TEMPLATE:
        raise ValidationError(
            _("%(count)d combinaisons depassent le seuil maximal de %(max)d variantes.")
            % {"count": len(combinations), "max": MAX_VARIANTS_PER_TEMPLATE}
        )

    created: list[ProductVariant] = []
    for combination in combinations:
        reference = next_reference(template.tenant, "VAR", timezone.now().year)
        variant = ProductVariant.objects.create(
            tenant=template.tenant, template=template, reference=reference
        )
        variant.attribute_values.set(combination)
        created.append(variant)

    return created
