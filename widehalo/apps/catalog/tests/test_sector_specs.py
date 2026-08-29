from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.catalog.models import CatalogSectorSpec, ProductTemplate, ProductVariant, UnitOfMeasure
from apps.catalog.services.sector_specs import create_sector_spec, validate_sector_attributes
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def variant_setup():
    tenant = Tenant.objects.create(code="CAT-SEC", name="Catalog Sector Spec Tenant")
    with use_tenant(tenant.id):
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PC", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )
        template = ProductTemplate.objects.create(
            tenant=tenant, name="Sac cuir", base_uom=uom, reference="TPL-SEC-0001"
        )
        variant = ProductVariant.objects.create(
            tenant=tenant, template=template, reference="VAR-SEC-0001"
        )
        return tenant, variant


# ---------------------------------------------------------------------------
# Validateurs par secteur
# ---------------------------------------------------------------------------


def test_cuir_requires_type_peau_and_valid_tannage() -> None:
    with pytest.raises(ValidationError):
        validate_sector_attributes(CatalogSectorSpec.SECTOR_CUIR, {"tannage": "vegetal"})
    with pytest.raises(ValidationError):
        validate_sector_attributes(
            CatalogSectorSpec.SECTOR_CUIR, {"type_peau": "chevre", "tannage": "inconnu"}
        )
    validate_sector_attributes(
        CatalogSectorSpec.SECTOR_CUIR, {"type_peau": "chevre", "tannage": "vegetal"}
    )


def test_cuir_epaisseur_must_be_a_positive_number() -> None:
    with pytest.raises(ValidationError):
        validate_sector_attributes(
            CatalogSectorSpec.SECTOR_CUIR,
            {"type_peau": "vache", "tannage": "chrome", "epaisseur_mm": -1},
        )
    with pytest.raises(ValidationError):
        validate_sector_attributes(
            CatalogSectorSpec.SECTOR_CUIR,
            {"type_peau": "vache", "tannage": "chrome", "epaisseur_mm": "epais"},
        )


def test_agroalimentaire_requires_conditions_conservation() -> None:
    with pytest.raises(ValidationError):
        validate_sector_attributes(CatalogSectorSpec.SECTOR_AGROALIMENTAIRE, {})
    validate_sector_attributes(
        CatalogSectorSpec.SECTOR_AGROALIMENTAIRE,
        {"conditions_conservation": "Sec, 20°C", "allergenes": ["arachide"]},
    )


def test_agroalimentaire_allergenes_must_be_a_list() -> None:
    with pytest.raises(ValidationError):
        validate_sector_attributes(
            CatalogSectorSpec.SECTOR_AGROALIMENTAIRE,
            {"conditions_conservation": "Sec", "allergenes": "arachide"},
        )


def test_artisanat_requires_matiere_and_technique() -> None:
    with pytest.raises(ValidationError):
        validate_sector_attributes(CatalogSectorSpec.SECTOR_ARTISANAT, {"technique": "tissage"})
    validate_sector_attributes(
        CatalogSectorSpec.SECTOR_ARTISANAT,
        {"matiere_premiere": "raphia", "technique": "tissage", "origine_artisan": "Antsirabe"},
    )


def test_import_export_is_never_a_valid_sector_code() -> None:
    """RG centrale du cadrage : `import_export` n'a delibrement aucun
    validateur — c'est deja couvert nativement par
    purchase/stocks/sales/logistics, zero code sectoriel necessaire."""
    with pytest.raises(ValidationError):
        validate_sector_attributes("import_export", {"anything": "goes"})


# ---------------------------------------------------------------------------
# `create_sector_spec` (service)
# ---------------------------------------------------------------------------


def test_create_sector_spec_persists_a_valid_cuir_spec(variant_setup) -> None:
    tenant, variant = variant_setup
    with use_tenant(tenant.id):
        spec = create_sector_spec(
            variant,
            sector_code=CatalogSectorSpec.SECTOR_CUIR,
            attributes={"type_peau": "chevre", "tannage": "vegetal", "epaisseur_mm": 1.2},
        )
        assert spec.variant_id == variant.id
        assert spec.sector_code == CatalogSectorSpec.SECTOR_CUIR
        assert CatalogSectorSpec.objects.filter(variant=variant).count() == 1


def test_create_sector_spec_rejects_invalid_attributes(variant_setup) -> None:
    tenant, variant = variant_setup
    with use_tenant(tenant.id):
        with pytest.raises(ValidationError):
            create_sector_spec(
                variant, sector_code=CatalogSectorSpec.SECTOR_CUIR, attributes={"tannage": "??"}
            )
        assert not CatalogSectorSpec.objects.filter(variant=variant).exists()


def test_variant_can_have_at_most_one_sector_spec(variant_setup) -> None:
    """`variant` est un `OneToOneField` — meme discipline que
    `TextileSpec`. `full_clean` (appele par `create_sector_spec`) leve une
    `ValidationError` sur la contrainte d'unicite avant meme d'atteindre la
    base (jamais une `IntegrityError` brute exposee a l'appelant)."""
    tenant, variant = variant_setup
    with use_tenant(tenant.id):
        create_sector_spec(
            variant,
            sector_code=CatalogSectorSpec.SECTOR_ARTISANAT,
            attributes={"matiere_premiere": "raphia", "technique": "tissage"},
        )
        with pytest.raises(ValidationError):
            create_sector_spec(
                variant,
                sector_code=CatalogSectorSpec.SECTOR_CUIR,
                attributes={"type_peau": "vache", "tannage": "chrome"},
            )
