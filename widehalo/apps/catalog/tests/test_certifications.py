from __future__ import annotations

import datetime as dt

import pytest

from apps.catalog.models import (
    CatalogCertification,
    CatalogStandard,
    ProductTemplate,
    ProductVariant,
    UnitOfMeasure,
)
from apps.catalog.services.public import get_valid_certifications
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def certification_setup():
    tenant = Tenant.objects.create(code="CAT-CERT", name="Catalog Certification Tenant")
    with use_tenant(tenant.id):
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="M", name="Metre", category=UnitOfMeasure.CATEGORY_LENGTH
        )
        template = ProductTemplate.objects.create(
            tenant=tenant, name="Coton bio", base_uom=uom, reference="TPL-CERT-0001"
        )
        variant = ProductVariant.objects.create(
            tenant=tenant, template=template, reference="VAR-CERT-0001"
        )
        standard = CatalogStandard.objects.create(
            tenant=tenant, code="GOTS", name="Global Organic Textile Standard"
        )
        return tenant, variant, standard


def test_valid_certification_is_returned(certification_setup) -> None:
    tenant, variant, standard = certification_setup
    with use_tenant(tenant.id):
        CatalogCertification.objects.create(
            tenant=tenant,
            variant=variant,
            standard=standard,
            valid_from=dt.date(2026, 1, 1),
            valid_until=dt.date(2027, 1, 1),
        )
        codes = get_valid_certifications(variant.id, on_date=dt.date(2026, 6, 1))
        assert codes == ["GOTS"]


def test_expired_certification_is_excluded(certification_setup) -> None:
    tenant, variant, standard = certification_setup
    with use_tenant(tenant.id):
        CatalogCertification.objects.create(
            tenant=tenant,
            variant=variant,
            standard=standard,
            valid_from=dt.date(2020, 1, 1),
            valid_until=dt.date(2021, 1, 1),
        )
        codes = get_valid_certifications(variant.id, on_date=dt.date(2026, 6, 1))
        assert codes == []


def test_certification_status_defaults_to_obtained(certification_setup) -> None:
    """QLT1-2 : le defaut `STATUS_OBTAINED` preserve le comportement suppose
    par toute certification creee avant l'ajout de ce champ (cf. docstring
    de `CatalogCertification`)."""
    tenant, variant, standard = certification_setup
    with use_tenant(tenant.id):
        certification = CatalogCertification.objects.create(
            tenant=tenant, variant=variant, standard=standard
        )
    assert certification.status == CatalogCertification.STATUS_OBTAINED


def test_certification_status_can_be_set_to_targeted_or_in_progress(certification_setup) -> None:
    tenant, variant, standard = certification_setup
    with use_tenant(tenant.id):
        targeted = CatalogCertification.objects.create(
            tenant=tenant,
            variant=variant,
            standard=standard,
            status=CatalogCertification.STATUS_TARGETED,
        )
    assert targeted.status == CatalogCertification.STATUS_TARGETED
