"""Tests de contraintes structurelles et d'interdependance (T2, CDC §8,
couches 4-5) pour le module `partners`. La RLS est hors perimetre (voir
`apps.core.tests.test_tenant_isolation`).

Note importante sur le NIF : `Partner.nif` n'est PAS unique en base
(volontairement, cf. docstring de `DuplicateAlert`) — deux fiches du meme
tenant peuvent partager le meme NIF (succursales, doublon a corriger a la
main...). Le mecanisme est une detection applicative non bloquante
(`DuplicateAlert`), deja couverte par
`test_partners.py::test_duplicate_nif_raises_an_alert_but_does_not_block_creation`.
On ne teste donc pas ici une contrainte DB d'unicite du NIF, qui n'existe
pas et ne doit pas exister."""

from __future__ import annotations

import pytest
from django.db.models.deletion import ProtectedError

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.partners.models import DuplicateAlert, Partner
from apps.partners.tests.factories import DuplicateAlertFactory, PartnerFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return Tenant.objects.create(code="PART-STRUCT", name="Partners Structural Tenant")


def test_deleting_a_tenant_with_partners_is_protected(tenant) -> None:
    """`BaseModel.tenant` est PROTECT — `Partner` en herite."""
    with use_tenant(tenant.id):
        PartnerFactory(tenant=tenant)

    with pytest.raises(ProtectedError):
        tenant.delete()


def test_deleting_the_partner_cascades_its_duplicate_alerts(tenant) -> None:
    with use_tenant(tenant.id):
        alert = DuplicateAlertFactory(tenant=tenant)
        partner_id = alert.partner_id
        alert_id = alert.id

        Partner.objects.filter(pk=partner_id).delete()

        assert not DuplicateAlert.objects.filter(pk=alert_id).exists()


def test_deleting_the_duplicate_of_partner_cascades_the_alert(tenant) -> None:
    with use_tenant(tenant.id):
        alert = DuplicateAlertFactory(tenant=tenant)
        duplicate_of_id = alert.duplicate_of_id
        alert_id = alert.id

        Partner.objects.filter(pk=duplicate_of_id).delete()

        assert not DuplicateAlert.objects.filter(pk=alert_id).exists()


def test_merging_a_partner_into_itself_deleted_sets_merged_into_null(tenant) -> None:
    """`Partner.merged_into` est `on_delete=SET_NULL` : si le partenaire
    absorbant est supprime physiquement, la reference sur les fiches
    absorbees est simplement videe (pas de suppression en cascade)."""
    with use_tenant(tenant.id):
        primary = PartnerFactory(tenant=tenant)
        absorbed = PartnerFactory(tenant=tenant, merged_into=primary)

        Partner.objects.filter(pk=primary.id).delete()

        absorbed.refresh_from_db()
        assert absorbed.merged_into_id is None
