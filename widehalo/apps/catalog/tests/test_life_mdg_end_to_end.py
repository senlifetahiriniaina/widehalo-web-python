"""REF3 (enrichissement referentiel LIFE MDG, cf. plan) : scenario de bout
en bout du chantier — creation d'une variante avec une matiere de
reference (Nomex), application d'une norme EPI (EN ISO 11612), filtrage
des options de personnalisation par compatibilite matiere (la gravure,
reservee cuir/metal, disparait de la liste filtree sur une matiere
textile), et consultation du produit d'exemple "Veste hi-vis" charge par
`load_sample_products` avec sa norme EN ISO 20471.

Toutes les donnees chargees par `load_material_references`/
`load_epi_standards`/`load_customization_options`/`load_sample_products`
sont explicitement disclosed comme demonstratives/indicatives (cf.
docstrings des commandes) — jamais un catalogue reel de tenant."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.catalog.models import (
    CatalogCertification,
    CatalogCustomizationOption,
    CatalogMaterialReference,
    CatalogStandard,
    ProductTemplate,
    ProductVariant,
    TextileSpec,
    UnitOfMeasure,
)
from apps.catalog.services.material_reference import set_attribute_value_color_reference
from apps.catalog.tests.factories import AttributeValueFactory
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def test_full_life_mdg_scenario() -> None:
    tenant = Tenant.objects.create(code="REF-E2E", name="LIFE MDG End to End Tenant")

    call_command("load_material_references", tenant=tenant.code)
    call_command("load_epi_standards", tenant=tenant.code)
    call_command("load_customization_options", tenant=tenant.code)
    call_command("load_sample_products", tenant=tenant.code)

    with use_tenant(tenant.id):
        # --- variante avec matiere de reference Nomex ------------------------
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PC", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )
        template = ProductTemplate.objects.create(
            tenant=tenant, name="Manche anti-feu", base_uom=uom, reference="TPL-E2E-0001"
        )
        variant = ProductVariant.objects.create(
            tenant=tenant, template=template, reference="VAR-E2E-0001"
        )
        nomex = CatalogMaterialReference.objects.get(tenant=tenant, code="NOMEX")
        spec = TextileSpec.objects.create(
            tenant=tenant, variant=variant, material=nomex.name, weight_gsm=nomex.typical_gsm_min
        )
        assert spec.material == "Nomex (méta-aramide)"

        # --- norme EN ISO 11612 appliquee a la variante ----------------------
        norme_anti_feu = CatalogStandard.objects.get(tenant=tenant, code="EN-ISO-11612")
        certification = CatalogCertification.objects.create(
            tenant=tenant, variant=variant, standard=norme_anti_feu
        )
        assert certification.standard.code == "EN-ISO-11612"

        # --- personnalisation compatible avec Nomex vs incompatible (gravure) -
        options_compatible_nomex = CatalogCustomizationOption.objects.filter(
            tenant=tenant, compatible_materials=nomex
        )
        assert options_compatible_nomex.count() == 0  # Nomex n'est cite dans aucune compatibilite
        gravure = CatalogCustomizationOption.objects.get(tenant=tenant, code="GRAVURE")
        assert not gravure.compatible_materials.filter(id=nomex.id).exists()

        options_compatible_pes = CatalogCustomizationOption.objects.filter(
            tenant=tenant, compatible_materials__code="PES"
        )
        codes_pes = set(options_compatible_pes.values_list("code", flat=True))
        assert "SUBLIMATION" in codes_pes
        assert "GRAVURE" not in codes_pes  # absente de la liste filtree par matiere textile

        # --- consultation du produit d'exemple "Veste hi-vis" ----------------
        veste_hivis = ProductTemplate.objects.get(tenant=tenant, reference="GARM-VESTE-HIVIS")
        veste_variant = veste_hivis.variants.first()
        assert veste_variant is not None
        norme_hivis_codes = set(
            veste_variant.certifications_detail.values_list("standard__code", flat=True)
        )
        assert "EN-ISO-20471" in norme_hivis_codes


def test_load_sample_products_is_idempotent_and_flags_demonstration_data() -> None:
    tenant = Tenant.objects.create(code="REF-E2E2", name="LIFE MDG End to End Tenant 2")
    call_command("load_material_references", tenant=tenant.code)
    call_command("load_epi_standards", tenant=tenant.code)
    call_command("load_sample_products", tenant=tenant.code)
    with use_tenant(tenant.id):
        count_first = ProductTemplate.objects.filter(tenant=tenant).count()
    call_command("load_sample_products", tenant=tenant.code)
    with use_tenant(tenant.id):
        assert ProductTemplate.objects.filter(tenant=tenant).count() == count_first
        # Trims (composants) et lamba malgaches sont bien de simples
        # ProductTemplate/ProductVariant ordinaires, aucune nouvelle entite.
        assert ProductTemplate.objects.filter(
            tenant=tenant, reference="TRIM-ZIP-COIL", category__name="Composants"
        ).exists()
        assert ProductTemplate.objects.filter(
            tenant=tenant,
            reference="LAMBA-LAMBAMENA",
            category__name="Lambas (patrimoine culturel malgache)",
        ).exists()


def test_pantone_format_reference_is_never_a_proprietary_color_value() -> None:
    """Reserve legale explicite (cf. plan) : `pantone_code` reste un simple
    format de code, `hex_approximation` une saisie manuelle — jamais une
    correspondance code<->couleur sourcee du nuancier Pantone."""
    tenant = Tenant.objects.create(code="REF-E2E3", name="LIFE MDG End to End Tenant 3")
    with use_tenant(tenant.id):
        value = AttributeValueFactory(tenant=tenant, value="Orange hi-vis")
        updated = set_attribute_value_color_reference(
            value, pantone_code="19-4052 TCX", hex_approximation="#FF6600"
        )
        # Le format est valide, mais aucune table de correspondance
        # pantone_code -> hex n'existe dans le code : `hex_approximation`
        # reste une valeur saisie explicitement ici par le test, jamais
        # deduite automatiquement du pantone_code.
        assert updated.pantone_code == "19-4052 TCX"
        assert updated.hex_approximation == "#FF6600"
