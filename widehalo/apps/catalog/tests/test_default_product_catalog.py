"""Chantier « catalogue par defaut des produits » : 30 EPI/vetements
techniques fabricables a Madagascar (Volet 2 du document source, perimetre
coupe-couture-ennoblissement), charges par `load_default_product_catalog`
-- un VRAI catalogue de tenant, jamais une fixture de demonstration
(contrairement a `load_sample_products`/`sample_products_by_family.json`,
qui reste intact et non wire a l'initialisation reelle)."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.catalog.models import (
    CatalogCertification,
    ProductTemplate,
    TextileSpec,
)
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def _load(tenant: Tenant) -> None:
    call_command("load_material_references", tenant=tenant.code)
    call_command("load_epi_standards", tenant=tenant.code)
    call_command("load_customization_options", tenant=tenant.code)
    call_command("load_default_product_catalog", tenant=tenant.code)


def test_load_default_product_catalog_creates_thirty_templates() -> None:
    tenant = Tenant.objects.create(code="CAT-DEF-01", name="Default Catalog Tenant")
    _load(tenant)

    with use_tenant(tenant.id):
        assert ProductTemplate.objects.filter(tenant=tenant).count() == 30
        # Toutes les templates ont un prix positif (jamais 0 -- converti
        # depuis le prix de vente indicatif export UE du document source).
        for template in ProductTemplate.objects.filter(tenant=tenant):
            assert template.base_price_mga > 0
            # Les produits du catalogue par defaut auto-charges sont
            # marques non vendables -- un administrateur les rebascule
            # explicitement une fois leur fiche verifiee/completee.
            assert template.is_sellable is False


def test_load_default_product_catalog_is_idempotent() -> None:
    tenant = Tenant.objects.create(code="CAT-DEF-02", name="Idempotence Tenant")
    _load(tenant)
    _load(tenant)

    with use_tenant(tenant.id):
        assert ProductTemplate.objects.filter(tenant=tenant).count() == 30


def test_default_product_catalog_resolves_material_and_standards() -> None:
    tenant = Tenant.objects.create(code="CAT-DEF-03", name="Resolution Tenant")
    _load(tenant)

    with use_tenant(tenant.id):
        veste_hivis = ProductTemplate.objects.get(tenant=tenant, reference="CAT-HIVIS-01")
        variant = veste_hivis.variants.get()
        spec = TextileSpec.objects.get(tenant=tenant, variant=variant)
        assert spec.weight_gsm == 320
        assert CatalogCertification.objects.filter(
            tenant=tenant, variant=variant, standard__code="EN-ISO-20471"
        ).exists()

        # Le manchon anti-coupure tricote n'a volontairement pas de
        # material_code (fibre HPPE absente du referentiel) -- aucune
        # TextileSpec fabriquee/devinee pour lui, mais sa norme EN-388 est
        # bien resolue.
        manchon = ProductTemplate.objects.get(tenant=tenant, reference="CAT-ACC-02")
        manchon_variant = manchon.variants.get()
        assert not TextileSpec.objects.filter(tenant=tenant, variant=manchon_variant).exists()
        assert CatalogCertification.objects.filter(
            tenant=tenant, variant=manchon_variant, standard__code="EN-388"
        ).exists()


def test_default_product_catalog_never_overlaps_the_demo_fixture() -> None:
    tenant = Tenant.objects.create(code="CAT-DEF-04", name="No Overlap Tenant")
    _load(tenant)
    call_command("load_sample_products", tenant=tenant.code)

    with use_tenant(tenant.id):
        default_refs = set(
            ProductTemplate.objects.filter(tenant=tenant, reference__startswith="CAT-").values_list(
                "reference", flat=True
            )
        )
        demo_refs = set(
            ProductTemplate.objects.filter(tenant=tenant)
            .exclude(reference__startswith="CAT-")
            .values_list("reference", flat=True)
        )
        assert len(default_refs) == 30
        assert default_refs.isdisjoint(demo_refs)
