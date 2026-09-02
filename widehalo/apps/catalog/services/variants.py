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
from apps.catalog.services.barcodes import assign_ean13
from apps.core.services.sequences import next_reference


def set_variant_attributes(template: ProductTemplate, attribute_ids: list[Any]) -> None:
    """Fixe les attributs generateurs de variantes d'un template — refuse
    au-dela de 2 (regle bloquante du cahier des charges, pas une simple
    recommandation)."""
    if len(attribute_ids) > MAX_VARIANT_GENERATING_ATTRIBUTES:
        raise ValidationError(
            _("Au maximum %(max)d attributs générateurs de variantes par gamme.")
            % {"max": MAX_VARIANT_GENERATING_ATTRIBUTES}
        )
    template.variant_attributes.set(attribute_ids)


def generate_variants(template: ProductTemplate) -> list[ProductVariant]:
    """Genere le produit cartesien des valeurs des attributs generateurs de
    variantes du template. Refuse au-dela de 50 combinaisons (seuil
    bloquant du cahier des charges) — AUCUNE variante n'est creee si le
    total depasse le seuil (tout ou rien, comme l'import de donnees).

    **INT1 (chantier interactivite native inter-modules)** : publie
    `catalog.variants_generated` apres creation reelle des variantes — rien
    n'est publie si `combinations` est vide (aucune variante creee, jamais
    un evenement vide) ni si le seuil est depasse (l'exception est levee
    avant toute creation, cf. ci-dessus)."""
    from django.utils import timezone

    attributes = list(template.variant_attributes.all())
    value_lists = [list(attribute.values.all()) for attribute in attributes]
    combinations = list(product(*value_lists)) if value_lists else []

    if len(combinations) > MAX_VARIANTS_PER_TEMPLATE:
        raise ValidationError(
            _("%(count)d combinaisons dépassent le seuil maximal de %(max)d variantes.")
            % {"count": len(combinations), "max": MAX_VARIANTS_PER_TEMPLATE}
        )

    created: list[ProductVariant] = []
    for combination in combinations:
        reference = next_reference(template.tenant, "VAR", timezone.now().year)
        variant = ProductVariant.objects.create(
            tenant=template.tenant, template=template, reference=reference
        )
        variant.attribute_values.set(combination)
        # T1 refonte UX (Sprint 4 / L3) : code-barres EAN-13/GTIN genere
        # automatiquement a la creation, jamais une etape manuelle
        # separee -- cf. apps.catalog.services.barcodes.
        assign_ean13(variant)
        created.append(variant)

    if created:
        from apps.core.events import publish_event

        publish_event(
            "catalog.variants_generated",
            {
                "template_id": str(template.id),
                "template_name": template.name,
                "variant_ids": [str(variant.id) for variant in created],
                "count": len(created),
            },
            tenant_id=str(template.tenant_id),
        )

    return created
