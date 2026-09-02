"""Tests du diff d'audit champ-par-champ sur `Partner` (chantier "fiche
partenaire a onglets par role", PT11) — verifie a la fois le mecanisme
generique (`compute_field_diff`, additif/retrocompatible dans
`apps.core.audit_signals`) et son branchement specifique sur
`Partner.save()`."""

from __future__ import annotations

import pytest
from django.contrib.contenttypes.models import ContentType

from apps.core.models.audit import AuditLog
from apps.core.services.audit import compute_field_diff
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant
from apps.partners.models import Partner
from apps.partners.services.onboarding import create_partner

pytestmark = pytest.mark.django_db


def test_compute_field_diff_scalar() -> None:
    diff = compute_field_diff(
        {"name": "A", "credit_limit_mga": 100}, {"name": "B", "credit_limit_mga": 100}
    )
    assert diff == {"name": {"before": "A", "after": "B"}}


def test_compute_field_diff_list_field_added_removed() -> None:
    diff = compute_field_diff({"roles": ["client", "carrier"]}, {"roles": ["client", "supplier"]})
    assert diff == {"roles": {"added": ["supplier"], "removed": ["carrier"]}}


def test_compute_field_diff_ignores_unchanged_and_unknown_fields() -> None:
    diff = compute_field_diff({"name": "A", "extra": 1}, {"name": "A"})
    assert diff == {}


def test_partner_creation_does_not_produce_a_diff() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        partner = create_partner(tenant=tenant, name="Textiles Sarl", roles=[Partner.ROLE_CLIENT])

        entry = AuditLog.objects.get(
            content_type=ContentType.objects.get_for_model(Partner),
            object_id=str(partner.id),
            action=AuditLog.ACTION_CREATED,
        )
        assert entry.changes == {}


def test_partner_update_produces_a_readable_diff() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        partner = create_partner(tenant=tenant, name="Textiles Sarl", roles=[Partner.ROLE_CLIENT])

        partner.name = "Textiles Sarl Bis"
        partner.roles = [Partner.ROLE_CLIENT, Partner.ROLE_SUPPLIER]
        partner.save()

        entry = (
            AuditLog.objects.filter(object_id=str(partner.id), action=AuditLog.ACTION_UPDATED)
            .order_by("-created_at")
            .first()
        )
        assert entry is not None
        assert entry.changes["name"] == {
            "before": "Textiles Sarl",
            "after": "Textiles Sarl Bis",
        }
        assert entry.changes["roles"] == {"added": ["supplier"], "removed": []}


def test_partner_update_with_no_tracked_field_change_produces_empty_diff() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        partner = create_partner(tenant=tenant, name="Textiles Sarl", roles=[Partner.ROLE_CLIENT])

        # Re-save without touching any of the 4 tracked fields.
        partner.save()

        entry = (
            AuditLog.objects.filter(object_id=str(partner.id), action=AuditLog.ACTION_UPDATED)
            .order_by("-created_at")
            .first()
        )
        assert entry is not None
        assert entry.changes == {}


def test_unrelated_basemodel_still_produces_an_empty_changes_dict() -> None:
    """Non-regression explicite du signal partage
    (`apps.core.audit_signals._on_save`) : un modele `BaseModel` qui ne
    pose jamais `_audit_diff` (l'immense majorite du depot — ici
    `PartnerContact`, qui n'a pas de `save()` surcharge) continue de
    produire `changes={}`, exactement comme avant PT11."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        partner = create_partner(tenant=tenant, name="Textiles Sarl", roles=[Partner.ROLE_CLIENT])
        contact = partner.contacts.create(tenant=tenant, full_name="Jean Dupont")
        contact.full_name = "Jean Dupont Bis"
        contact.save()

        entry = (
            AuditLog.objects.filter(
                content_type=ContentType.objects.get_for_model(contact),
                object_id=str(contact.id),
                action=AuditLog.ACTION_UPDATED,
            )
            .order_by("-created_at")
            .first()
        )
        assert entry is not None
        assert entry.changes == {}
